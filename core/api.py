"""Web API handlers exposed to the plugin Page via ``context.register_web_api``.

所有 handler 均为 ``WebApiMixin`` 的方法，路由在 ``__init__`` 中通过
``self.context.register_web_api()`` 注册，与 meme_manager 架构一致。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import mimetypes
import time
from typing import Any

from quart import jsonify, request, send_file

from .manager import MemeManager
from .storage import is_image_filename, memes_dir, safe_join

logger = logging.getLogger(__name__)

PLUGIN_NAME = "astrbot_plugin_randommeme"
WEBUI_LOG_PREFIX = f"[{PLUGIN_NAME}][WebUI]"


class WebApiMixin:
    """Mixin that registers all plugin Web API routes on ``self.context``."""

    manager: MemeManager

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _data(payload: Any, status_code: int = 200):
        return jsonify({"status": "ok", "data": payload}), status_code

    @staticmethod
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

    @staticmethod
    def _all_groups_payload(manager: MemeManager) -> list[dict[str, Any]]:
        return [WebApiMixin._group_payload(manager, g.name) for g in manager.list_groups()]

    @staticmethod
    def _require_group(manager: MemeManager, name: str):
        g = manager.get_group(name)
        if not g:
            return None, (
                jsonify({"status": "error", "message": f"组别不存在: {name}"}),
                404,
            )
        return g, None

    @staticmethod
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

    # ------------------------------------------------------------- registration

    def _register_webui_api(self, route: str, handler, methods: list[str], desc: str):
        """注册单个 Web API 路由（与 meme_manager 完全一致的包装模式）。"""
        route_path = f"/{PLUGIN_NAME}/{route.strip('/')}"

        async def logged_handler(*args, **kwargs):
            started_at = time.monotonic()
            logger.info(f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 开始")
            try:
                response = await handler(*args, **kwargs)
            except Exception:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                logger.error(
                    f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 失败 耗时={elapsed_ms}ms",
                    exc_info=True,
                )
                raise
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            status_code = self._get_response_status(response)
            logger.info(
                f"{WEBUI_LOG_PREFIX} {request.method} {route_path} 完成 状态={status_code} 耗时={elapsed_ms}ms"
            )
            return response

        logged_handler.__name__ = f"webui_{handler.__name__}"
        self.context.register_web_api(route_path, logged_handler, methods, desc)

    @staticmethod
    def _get_response_status(response) -> int | str:
        if isinstance(response, tuple) and len(response) > 1:
            return response[1]
        return getattr(response, "status_code", "unknown")

    def _register_web_apis(self) -> None:
        """注册全部 API 路由。"""

        # ----- groups -----
        self._register_webui_api(
            "groups",
            self._api_groups,
            ["GET", "POST"],
            "List / Create groups",
        )
        self._register_webui_api(
            "groups/<name>",
            self._api_get_group,
            ["GET"],
            "Get group",
        )
        self._register_webui_api(
            "groups/<name>/update",
            self._api_update_group,
            ["POST"],
            "Update group",
        )
        self._register_webui_api(
            "groups/<name>/delete",
            self._api_delete_group,
            ["POST"],
            "Delete group",
        )
        # ----- images -----
        self._register_webui_api(
            "groups/<name>/images",
            self._api_group_images,
            ["GET", "POST"],
            "List / Upload images",
        )
        self._register_webui_api(
            "groups/<name>/images/delete",
            self._api_delete_images,
            ["POST"],
            "Delete images",
        )
        self._register_webui_api(
            "groups/<name>/images/data/<filename>",
            self._api_image_data,
            ["GET"],
            "Get image as base64 data URL",
        )
        self._register_webui_api(
            "groups/<name>/images/<path:filename>",
            self._api_fetch_image,
            ["GET"],
            "Fetch raw image",
        )
        # ----- history -----
        self._register_webui_api(
            "groups/<name>/reset",
            self._api_reset_group_history,
            ["POST"],
            "Reset group draw history",
        )
        self._register_webui_api(
            "reset",
            self._api_reset_all_history,
            ["POST"],
            "Reset all",
        )
        # ----- meta -----
        self._register_webui_api(
            "stats",
            self._api_get_stats,
            ["GET"],
            "Get stats",
        )

    # ------------------------------------------------------------- handlers

    async def _api_groups(self):
        if request.method == "GET":
            return self._data({"groups": self._all_groups_payload(self.manager)})
        # POST — create
        body = (await request.get_json(silent=True)) or {}
        name = str(body.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少 name"}), 400
        aliases_raw = body.get("aliases") or []
        if not isinstance(aliases_raw, list):
            return jsonify({"status": "error", "message": "aliases 必须是列表"}), 400
        require_wake = bool(body.get("require_wake") or False)
        try:
            group = await self.manager.create_group(
                name, aliases=aliases_raw, require_wake=require_wake
            )
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return self._data(self._group_payload(self.manager, group.name), status_code=201)

    async def _api_get_group(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        return self._data(self._group_payload(self.manager, g.name))

    async def _api_update_group(self, name: str):
        g, err = self._require_group(self.manager, name)
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
            await self.manager.update_group(g.name, **kwargs)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return self._data(self._group_payload(self.manager, g.name))

    async def _api_delete_group(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        deleted = await self.manager.delete_group(g.name)
        if not deleted:
            return jsonify({"status": "error", "message": "删除失败"}), 500
        return self._data({"deleted": g.name})

    async def _api_group_images(self, name: str):
        if request.method == "GET":
            return await self._api_list_images(name)
        return await self._api_upload_images(name)

    async def _api_list_images(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        return self._data({"images": self.manager.list_images(g.name)})

    async def _api_upload_images(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err

        uploads: list[tuple[str, bytes]] = []

        # 1) JSON body with base64-encoded content (bridge.apiPost)
        body = (await request.get_json(silent=True)) or {}
        if isinstance(body, dict) and body.get("content_base64"):
            filename = str(body.get("filename") or "upload.png")
            mime_type = str(body.get("mime_type") or "image/png")
            if not is_image_filename(filename, gif_support=self.manager.gif_support):
                ext = mimetypes.guess_extension(mime_type) or ".png"
                filename = f"upload{ext}"
            try:
                payload = base64.b64decode(body["content_base64"])
            except (binascii.Error, ValueError):
                return jsonify({"status": "error", "message": "Base64 解码失败"}), 400
            if payload:
                uploads.append((filename, payload))

        # 2) Fallback: multipart form upload (bridge.upload)
        if not uploads:
            files = await request.files
            if files:
                for upload in files.values():
                    try:
                        payload = upload.read()
                    finally:
                        upload.close()
                    if payload:
                        uploads.append((upload.filename or "upload.bin", payload))

        if not uploads:
            return jsonify(
                {"status": "error", "message": "没有有效图片内容"}
            ), 400
        try:
            stored = await self.manager.add_images(g.name, uploads)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return self._data({"stored": stored}, status_code=201)

    async def _api_delete_images(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        body = (await request.get_json(silent=True)) or {}
        filenames = self._normalize_filenames(body.get("filenames"))
        if not filenames:
            return jsonify({"status": "error", "message": "缺少 filenames"}), 400
        try:
            removed = await self.manager.delete_images(g.name, filenames)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return self._data({"removed": removed})

    async def _api_image_data(self, name: str, filename: str = ""):
        """Return image as base64 JSON for sandbox-safe preview."""
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        if not filename:
            return jsonify({"status": "error", "message": "缺少 filename"}), 400
        if not is_image_filename(filename, gif_support=self.manager.gif_support):
            return jsonify({"status": "error", "message": "文件类型不受支持"}), 400
        try:
            target = safe_join(memes_dir(g.name), filename)
        except ValueError:
            return jsonify({"status": "error", "message": "非法路径"}), 400
        if not target.is_file():
            return jsonify({"status": "error", "message": "文件不存在"}), 404
        ctype, _ = mimetypes.guess_type(target.name)
        payload = await asyncio.to_thread(target.read_bytes)
        return self._data({
            "filename": filename,
            "mime_type": ctype or "application/octet-stream",
            "content_base64": base64.b64encode(payload).decode("ascii"),
        })

    async def _api_fetch_image(self, name: str, filename: str = ""):
        """Serve an individual image file from ``memes/<group>`` for previews."""
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        if not filename:
            return jsonify({"status": "error", "message": "缺少 filename"}), 400
        if not is_image_filename(filename, gif_support=self.manager.gif_support):
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

    async def _api_reset_group_history(self, name: str):
        g, err = self._require_group(self.manager, name)
        if err is not None:
            return err
        count = await self.manager.reset_history(g.name)
        return self._data({"reset": g.name, "was_present": bool(count)})

    async def _api_reset_all_history(self):
        count = await self.manager.reset_history(None)
        return self._data({"reset_all": True, "groups_cleared": count})

    async def _api_get_stats(self):
        groups = self.manager.list_groups()
        return self._data(
            {
                "group_count": len(groups),
                "image_total": sum(self.manager.image_count(g.name) for g in groups),
                "history_size": sum(len(v) for v in self.manager._history.values()),  # noqa: SLF001
                "groups": [
                    {
                        "name": g.name,
                        "image_count": self.manager.image_count(g.name),
                        "drew": len(self.manager._history.get(g.name, [])),  # noqa: SLF001
                    }
                    for g in groups
                ],
            }
        )
