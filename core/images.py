"""从聊天消息中提取图片并转为 (filename, bytes) 列表。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


def _iter_message_components(event: Any) -> list[Any]:
    """收集当前消息与 Reply 引用链中的组件。"""
    messages: list[Any] = []
    get_messages = getattr(event, "get_messages", None)
    if callable(get_messages):
        try:
            messages = list(get_messages() or [])
        except Exception:
            messages = []
    if not messages:
        msg_obj = getattr(event, "message_obj", None)
        messages = list(getattr(msg_obj, "message", None) or [])

    out: list[Any] = []
    for comp in messages:
        out.append(comp)
        chain = getattr(comp, "chain", None)
        if chain:
            out.extend(list(chain))
    return out


def _is_image_component(comp: Any) -> bool:
    if comp is None:
        return False
    if type(comp).__name__ == "Image":
        return True
    if hasattr(comp, "convert_to_file_path") and (
        getattr(comp, "url", None)
        or getattr(comp, "file", None)
        or getattr(comp, "path", None)
    ):
        return True
    return False


def collect_image_components(event: Any) -> list[Any]:
    """从 event 中收集所有 Image 组件（含 Reply 引用）。"""
    return [c for c in _iter_message_components(event) if _is_image_component(c)]


def _local_path_from_file_field(file_field: str) -> str | None:
    if not file_field:
        return None
    if file_field.startswith("file:"):
        parsed = urlparse(file_field)
        path = unquote(parsed.path or "")
        # Windows: file:///C:/x -> /C:/x -> C:/x
        if path.startswith("/") and len(path) > 2 and path[2] == ":":
            path = path[1:]
        return path or None
    p = Path(file_field)
    if p.is_file():
        return str(p)
    return None


async def image_component_to_bytes(comp: Any) -> tuple[str, bytes] | None:
    """将单个 Image 组件转为 (filename, content)。失败返回 None。"""
    try:
        path: str | None = None
        convert = getattr(comp, "convert_to_file_path", None)
        if callable(convert):
            try:
                path = await convert()
            except Exception:
                logger.exception("[randommeme] convert_to_file_path failed")
                path = None

        if not path:
            candidate = getattr(comp, "path", None)
            if candidate and Path(str(candidate)).is_file():
                path = str(candidate)

        if not path:
            file_field = getattr(comp, "file", None) or ""
            if isinstance(file_field, str):
                path = _local_path_from_file_field(file_field)

        if not path:
            logger.warning("[randommeme] image component has no resolvable path/url")
            return None

        p = Path(path)
        if not p.is_file():
            logger.warning("[randommeme] image path not found: %s", path)
            return None

        content = await asyncio.to_thread(p.read_bytes)
        if not content:
            return None

        ext = p.suffix.lower() or ".png"
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
            ext = ".png"
        filename = f"chat_{int(time.time())}_{p.stem[:24]}{ext}"
        return filename, content
    except Exception:
        logger.exception("[randommeme] failed to resolve image component")
        return None


async def extract_image_uploads(event: Any) -> list[tuple[str, bytes]]:
    """提取消息内全部图片为 add_images 所需的 uploads 列表。"""
    uploads: list[tuple[str, bytes]] = []
    for comp in collect_image_components(event):
        item = await image_component_to_bytes(comp)
        if item:
            uploads.append(item)
    return uploads
