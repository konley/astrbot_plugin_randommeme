"""Web API handlers exposed to the plugin Page via ``context.register_web_api``.

Base path: ``/astrbot_plugin_randommeme`` (plugin name prefix).

Bridge SDK only exposes ``apiGet`` (GET) and ``apiPost`` (POST). All other
operations (delete, update) are therefore exposed as POST endpoints with a
``_method`` query override so the WebUI can still use plain HTTP verbs later
if the dashboard ever supports more.

Conventions:
- JSON success: ``{"status": "ok", "data": {...}}``.
- JSON error  : ``{"status": "error", "message": "..."}`` with non-2xx status.
- All filename / group-name inputs are validated before touching the manager
  or filesystem.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import Any

from quart import jsonify, request, send_file

from .manager import MemeManager
from .storage import is_image_filename, memes_dir, safe_join

logger = logging.getLogger(__name__)

PLUGIN_ROUTE_PREFIX = "/astrbot_plugin_randommeme"


# --------------------------------------------------------------- helpers


def _data(payload: Any, status_code: int = 200):
    return jsonify({"status": "ok", "data": payload}), status_code


def _group_payload(manager: MemeManager, group_name: str) -> dict[str, Any]:
    g = manager.get_group(group_name)
    if not g:
        return {}
    return {
        "name": g.name,
        "aliases": list(g.aliases),
        "require_wake": g.require_wake,
        "enabled": g.enabled,
        "image_count": manager.image_count(g.name),
        "created_at": g.created_at,
    }


def _all_groups_payload(manager: MemeManager) -> list[dict[str, Any]]:
    return [_group_payload(manager, g.name) for g in manager.list_groups()]


def _require_group(manager: MemeManager, name: str):
    g = manager.get_group(name)
    if not g:
        return None, (
            jsonify({"status": "error", "message": f"组别不存在: {name}"}),
            404,
        )
    return g, None


def _normalize_filenames(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        candidate = item.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        out.append(candidate)
    return out


# --------------------------------------------------------------- handlers


async def list_groups(manager: MemeManager):
    return _data({"groups": _all_groups_payload(manager)})


async def create_group(manager: MemeManager):
    body = (await request.get_json(silent=True)) or {}
    name = str(body.get("name") or "").strip()
    if not name:
        return jsonify({"status": "error", "message": "缺少 name"}), 400
    aliases_raw = body.get("aliases") or []
    if not isinstance(aliases_raw, list):
        return jsonify({"status": "error", "message": "aliases 必须是列表"}), 400
    require_wake = bool(body.get("require_wake") or False)
    try:
        group = await manager.create_group(
            name, aliases=aliases_raw, require_wake=require_wake
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return _data(_group_payload(manager, group.name), status_code=201)


async def get_group(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    return _data(_group_payload(manager, g.name))


async def update_group(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    body = (await request.get_json(silent=True)) or {}
    kwargs: dict[str, Any] = {}
    if "aliases" in body:
        aliases = body["aliases"]
        if not isinstance(aliases, list):
            return jsonify({"status": "error", "message": "aliases 必须是列表"}), 400
        kwargs["aliases"] = aliases
    if "require_wake" in body:
        kwargs["require_wake"] = bool(body["require_wake"])
    if "enabled" in body:
        kwargs["enabled"] = bool(body["enabled"])
    try:
        await manager.update_group(g.name, **kwargs)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return _data(_group_payload(manager, g.name))


async def delete_group(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    deleted = await manager.delete_group(g.name)
    if not deleted:
        return jsonify({"status": "error", "message": "删除失败"}), 500
    return _data({"deleted": g.name})


async def list_images(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    return _data({"images": manager.list_images(g.name)})


async def upload_images(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    files = await request.files
    if not files:
        return jsonify(
            {"status": "error", "message": "缺少文件 (multipart field 'file')"}
        ), 400
    uploads: list[tuple[str, bytes]] = []
    for upload in files.values():
        try:
            payload = upload.read()
        finally:
            upload.close()
        if payload:
            uploads.append((upload.filename or "upload.bin", payload))
    if not uploads:
        return jsonify({"status": "error", "message": "没有有效图片内容"}), 400
    try:
        stored = await manager.add_images(g.name, uploads)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return _data({"stored": stored}, status_code=201)


async def delete_images(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    body = (await request.get_json(silent=True)) or {}
    filenames = _normalize_filenames(body.get("filenames"))
    if not filenames:
        return jsonify({"status": "error", "message": "缺少 filenames"}), 400
    try:
        removed = await manager.delete_images(g.name, filenames)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return _data({"removed": removed})


async def fetch_image(manager: MemeManager, name: str, filename: str = ""):
    """Serve an individual image file from ``memes/<group>`` for previews."""
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    if not filename:
        return jsonify({"status": "error", "message": "缺少 filename"}), 400
    if not is_image_filename(filename, gif_support=manager.gif_support):
        return jsonify({"status": "error", "message": "文件类型不受支持"}), 400
    try:
        target = safe_join(memes_dir(g.name), filename)
    except ValueError:
        return jsonify({"status": "error", "message": "非法路径"}), 400
    if not target.is_file():
        return jsonify({"status": "error", "message": "文件不存在"}), 404
    ctype, _ = mimetypes.guess_type(target.name)
    return await send_file(
        target,
        mimetype=ctype or "application/octet-stream",
        as_attachment=False,
        download_name=target.name,
    )


async def reset_group_history(manager: MemeManager, name: str):
    g, err = _require_group(manager, name)
    if err is not None:
        return err
    count = await manager.reset_history(g.name)
    return _data({"reset": g.name, "was_present": bool(count)})


async def reset_all_history(manager: MemeManager):
    count = await manager.reset_history(None)
    return _data({"reset_all": True, "groups_cleared": count})


async def get_stats(manager: MemeManager):
    groups = manager.list_groups()
    return _data(
        {
            "group_count": len(groups),
            "image_total": sum(manager.image_count(g.name) for g in groups),
            "history_size": sum(len(v) for v in manager._history.values()),  # noqa: SLF001
            "groups": [
                {
                    "name": g.name,
                    "image_count": manager.image_count(g.name),
                    "drew": len(manager._history.get(g.name, [])),  # noqa: SLF001
                }
                for g in groups
            ],
        }
    )


# --------------------------------------------------------------- registry


def register_web_apis(context, manager: MemeManager) -> None:
    """Attach all handlers to ``context``.

    The path parameter ``<name>`` is captured by the dashboard regex and passed
    to the handler as ``**kwargs``; we wrap with small async closures so the
    manager is captured once at registration time and so the dashboard sees a
    single stable handler reference.
    """

    def _bind(coro):
        async def wrapper(*args, **path_kwargs):
            return await coro(manager, *args, **path_kwargs)

        return wrapper

    def _bind_no_param(coro):
        async def wrapper(*args, **_path_kwargs):
            return await coro(manager, *args)

        return wrapper

    # ---- merged handlers to avoid duplicate route registration ----

    async def handle_groups(manager: MemeManager):
        if request.method == "GET":
            return await list_groups(manager)
        return await create_group(manager)

    async def handle_group_images(manager: MemeManager, name: str):
        if request.method == "GET":
            return await list_images(manager, name)
        return await upload_images(manager, name)

    # ---------------------------------------------------------------

    pairs = [
        # ----- groups -----
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups",
            _bind_no_param(handle_groups),
            ["GET", "POST"],
            "List / Create groups",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>",
            _bind(get_group),
            ["GET"],
            "Get group",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/update",
            _bind(update_group),
            ["POST"],
            "Update group",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/delete",
            _bind(delete_group),
            ["POST"],
            "Delete group",
        ),
        # ----- images -----
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/images",
            _bind(handle_group_images),
            ["GET", "POST"],
            "List / Upload images",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/images/delete",
            _bind(delete_images),
            ["POST"],
            "Delete images",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/images/<path:filename>",
            _bind(fetch_image),
            ["GET"],
            "Fetch raw image",
        ),
        # ----- history -----
        (
            f"{PLUGIN_ROUTE_PREFIX}/groups/<name>/reset",
            _bind(reset_group_history),
            ["POST"],
            "Reset group draw history",
        ),
        (
            f"{PLUGIN_ROUTE_PREFIX}/reset",
            _bind_no_param(reset_all_history),
            ["POST"],
            "Reset all",
        ),
        # ----- meta -----
        (
            f"{PLUGIN_ROUTE_PREFIX}/stats",
            _bind_no_param(get_stats),
            ["GET"],
            "Get stats",
        ),
    ]
    for route, handler, methods, desc in pairs:
        context.register_web_api(route, handler, methods, desc)
