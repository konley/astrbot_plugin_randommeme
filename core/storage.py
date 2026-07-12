"""存储路径工具与文件操作 helper。

所有持久化数据统一落在 ``data/plugin_data/astrbot_plugin_randommeme/`` 下，
目录结构::

    <plugin_data>/
        groups.json              # 组别元数据 + 抽取历史 (全局共享)
        memes/<group_name>/     # 各组别的图片
            aaa.jpg
            bbb.gif
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

PLUGIN_DIR_NAME = "astrbot_plugin_randommeme"
DATA_DIR_NAME = "memes"
STATE_FILE = "groups.json"

IMAGE_EXTS_STATIC = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
IMAGE_EXTS_GIF = {".gif"}
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,32}$")


def plugin_data_dir() -> Path:
    """Return the plugin's persistent data directory, creating it if needed."""
    base = Path(get_astrbot_plugin_data_path()) / PLUGIN_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def memes_dir(group_name: str) -> Path:
    """Return the directory for a group's images, creating it if needed."""
    group_dir = plugin_data_dir() / DATA_DIR_NAME / safe_group_name(group_name)
    group_dir.mkdir(parents=True, exist_ok=True)
    return group_dir


def safe_group_name(name: str) -> str:
    """Normalize a user-provided group name to a safe filesystem segment.

    Args:
        name: Raw group name from config or webui.

    Returns:
        A safe directory name matching ``_SAFE_NAME_RE``.

    Raises:
        ValueError: If the name is empty after normalization.
    """
    raw = (name or "").strip()
    if not raw:
        raise ValueError("组别名称不能为空")

    normalized = unicodedata.normalize("NFKC", raw)
    sanitized = normalized.replace(" ", "_")

    if not _SAFE_NAME_RE.match(sanitized):
        cleaned = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", sanitized)
        if not cleaned or not _SAFE_NAME_RE.match(cleaned):
            raise ValueError(f"非法组别名称: {name!r}")
        sanitized = cleaned

    return sanitized


def is_image_filename(filename: str, *, gif_support: bool) -> bool:
    """Return True if ``filename`` is an accepted image extension."""
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS_STATIC:
        return True
    if gif_support and ext in IMAGE_EXTS_GIF:
        return True
    return False


async def read_json(path: Path, default: Any) -> Any:
    """Read JSON from ``path``; return ``default`` if missing or invalid."""
    if not path.exists():
        return default
    try:
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except OSError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


async def write_json(path: Path, data: Any) -> None:
    """Atomically write JSON to ``path`` (UTF-8, no BOM)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    def _write() -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    await asyncio.to_thread(_write)


def safe_join(base: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base`` while preventing path traversal.

    Args:
        base: Trusted directory.
        parts: Path segments; each must not contain separators or ``..``.

    Returns:
        Resolved path that is guaranteed to live under ``base``.

    Raises:
        ValueError: If the resulting path escapes ``base``.
    """
    target = base.joinpath(*parts).resolve(strict=False)
    base_resolved = base.resolve(strict=False)
    target.relative_to(base_resolved)  # raises ValueError on escape
    return target
