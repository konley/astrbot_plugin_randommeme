"""核心管理器：组别/图片/抽取池/匹配。

内部状态修改 ``_groups``/``_history`` 都由 ``_lock`` 串行化；
文件 IO 走 ``asyncio.to_thread``，事件循环不会被阻塞。
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import shutil

from .group import Group, dump_state, normalize_state
from .storage import (
    STATE_FILE,
    is_image_filename,
    memes_dir,
    plugin_data_dir,
    read_json,
    safe_join,
    write_json,
)

logger = logging.getLogger(__name__)


class MemeManager:
    """In-memory group + draw pool manager backed by ``groups.json`` on disk."""

    STATE_FILE_NAME = STATE_FILE

    def __init__(self, *, gif_support: bool = True, exact_match: bool = False) -> None:
        self._gif_support = gif_support
        self._exact_match = exact_match
        self._lock = asyncio.Lock()
        self._groups: list[Group] = []
        self._history: dict[str, list[str]] = {}
        self._state_path = plugin_data_dir() / self.STATE_FILE_NAME

    # ------------------------------------------------------------ lifecycle

    async def load(self) -> None:
        async with self._lock:
            data = await read_json(self._state_path, default={})
            self._groups, self._history = normalize_state(data)
            self._prune_history_locked()
            await self._save_locked()

    # ------------------------------------------------------------ views

    @property
    def gif_support(self) -> bool:
        return self._gif_support

    @property
    def exact_match(self) -> bool:
        return self._exact_match

    def list_groups(self) -> list[Group]:
        return list(self._groups)

    def get_group(self, name: str) -> Group | None:
        target = (name or "").strip()
        for g in self._groups:
            if g.name == target:
                return g
        return None

    def match_group(self, text: str) -> Group | None:
        """Return the group whose keyword appears in ``text``.

        Fuzzy mode (default): keyword only needs to appear anywhere in text;
        longest matching keyword wins when multiple groups match.
        Exact mode: the whole text must equal the keyword (case-insensitive).
        """
        token = (text or "").strip()
        if not token:
            return None
        lowered = token.casefold()
        best: tuple[int, Group] | None = None  # (kw_len, group)
        for g in self._groups:
            if not g.enabled:
                continue
            for kw in g.all_keywords():
                kw_lower = kw.casefold()
                if self._exact_match:
                    if kw_lower == lowered:
                        return g
                elif kw_lower in lowered:
                    kw_len = len(kw_lower)
                    if best is None or kw_len > best[0]:
                        best = (kw_len, g)
        return best[1] if best else None

    # ------------------------------------------------------------ images

    def list_images(self, group_name: str) -> list[str]:
        if not self.get_group(group_name):
            return []
        gdir = memes_dir(group_name)
        if not gdir.exists():
            return []
        files = [
            p.name
            for p in gdir.iterdir()
            if p.is_file() and is_image_filename(p.name, gif_support=self._gif_support)
        ]
        return sorted(files)

    def image_count(self, group_name: str) -> int:
        return len(self.list_images(group_name))

    async def add_images(
        self, group_name: str, uploads: list[tuple[str, bytes]]
    ) -> list[str]:
        async with self._lock:
            if not self.get_group(group_name):
                raise ValueError(f"组别不存在: {group_name}")
            gdir = memes_dir(group_name)
            existing = {p.name for p in gdir.iterdir() if p.is_file()}
            stored: list[str] = []
            for original, content in uploads:
                if not original or not content:
                    continue
                if not is_image_filename(original, gif_support=self._gif_support):
                    continue
                name = self._safe_filename(original)
                name = self._dedupe_filename(name, existing)
                target = gdir / name
                await asyncio.to_thread(target.write_bytes, content)
                stored.append(name)
                existing.add(name)
            if stored:
                await self._save_locked()
            return stored

    async def delete_images(self, group_name: str, filenames: list[str]) -> list[str]:
        async with self._lock:
            if not self.get_group(group_name):
                raise ValueError(f"组别不存在: {group_name}")
            gdir = memes_dir(group_name)
            removed: list[str] = []
            for name in filenames:
                if not name:
                    continue
                try:
                    target = safe_join(gdir, name)
                except ValueError:
                    continue
                if target.is_file():
                    try:
                        await asyncio.to_thread(target.unlink)
                    except OSError:
                        continue
                    removed.append(target.name)
            if removed:
                self._drop_history_locked(group_name, set(removed))
                await self._save_locked()
            return removed

    # ------------------------------------------------------------ groups

    async def create_group(
        self,
        name: str,
        *,
        aliases: list[str] | None = None,
        require_wake: bool = False,
    ) -> Group:
        async with self._lock:
            name = (name or "").strip()
            self._validate_name_locked(name)
            cleaned_aliases = self._validate_aliases_locked(name, aliases or [])
            group = Group(
                name=name,
                aliases=cleaned_aliases,
                require_wake=require_wake,
                enabled=True,
            )
            self._groups.append(group)
            await self._save_locked()
            memes_dir(name)
            return group

    async def update_group(
        self,
        name: str,
        *,
        aliases: list[str] | None = None,
        require_wake: bool | None = None,
        enabled: bool | None = None,
    ) -> Group:
        async with self._lock:
            group = self.get_group(name)
            if not group:
                raise ValueError(f"组别不存在: {name}")
            if require_wake is not None:
                group.require_wake = bool(require_wake)
            if enabled is not None:
                group.enabled = bool(enabled)
            if aliases is not None:
                group.aliases = self._validate_aliases_locked(name, aliases)
            await self._save_locked()
            return group

    async def delete_group(self, name: str) -> bool:
        async with self._lock:
            group = self.get_group(name)
            if not group:
                return False
            gdir = memes_dir(name)
            await asyncio.to_thread(shutil.rmtree, gdir, ignore_errors=True)
            self._groups = [g for g in self._groups if g.name != name]
            self._history.pop(name, None)
            await self._save_locked()
            return True

    async def reset_history(self, name: str | None = None) -> int:
        async with self._lock:
            if name is None:
                count = len(self._history)
                self._history.clear()
            else:
                count = 0 if name not in self._history else 1
                self._history.pop(name, None)
            await self._save_locked()
            return count

    def get_history_size(self) -> int:
        """Total number of draws across all groups in the current round."""
        return sum(len(v) for v in self._history.values())

    def get_group_drew_count(self, name: str) -> int:
        """Number of draws for a specific group in the current round."""
        return len(self._history.get(name, []))

    # ------------------------------------------------------------ draw

    async def draw(self, group_name: str) -> str | None:
        async with self._lock:
            group = self.get_group(group_name)
            if not group:
                return None
            available = self.list_images(group.name)
            if not available:
                return None

            seen = set(self._history.get(group.name, []))
            remaining = [n for n in available if n not in seen]
            if not remaining:
                self._history[group.name] = []
                remaining = list(available)

            pick = random.SystemRandom().choice(remaining)
            self._history.setdefault(group.name, []).append(pick)
            self._prune_history_for_group_locked(group.name)
            await self._save_locked()
            return str(memes_dir(group.name) / pick)

    # ------------------------------------------------------------ internals

    def _prune_history_locked(self) -> None:
        valid_groups = {g.name for g in self._groups}
        for name in list(self._history.keys()):
            self._prune_history_for_group_locked(name)
        self._history = {k: v for k, v in self._history.items() if k in valid_groups}

    def _prune_history_for_group_locked(self, name: str) -> None:
        if name not in self._history:
            return
        valid = set(self.list_images(name))
        self._history[name] = [n for n in self._history[name] if n in valid]
        if not self._history[name]:
            self._history.pop(name, None)

    def _drop_history_locked(self, name: str, removed: set[str]) -> None:
        if name not in self._history:
            return
        self._history[name] = [n for n in self._history[name] if n not in removed]
        if not self._history[name]:
            self._history.pop(name, None)

    def _validate_name_locked(self, name: str) -> None:
        if not name:
            raise ValueError("组别名称不能为空")
        if any(g.name == name for g in self._groups):
            raise ValueError(f"组别已存在: {name}")

    def _validate_aliases_locked(self, name: str, aliases: list[str]) -> list[str]:
        cleaned = [str(a).strip() for a in aliases if str(a).strip()]
        own_lower = {name.casefold()}
        cleaned_lower = {c.casefold() for c in cleaned}
        for g in self._groups:
            if g.name == name:
                continue
            for kw in g.all_keywords():
                other = kw.casefold()
                if other in own_lower or other in cleaned_lower:
                    raise ValueError(f"别名与现有组别冲突: {kw}")
        return cleaned

    async def _save_locked(self) -> None:
        await write_json(self._state_path, dump_state(self._groups, self._history))

    @staticmethod
    def _safe_filename(name: str) -> str:
        base = os.path.basename((name or "").strip())
        if not base:
            base = f"upload_{os.urandom(2).hex()}.bin"
        stem, ext = os.path.splitext(base)
        safe_stem = (
            re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", stem).strip("._") or "upload"
        )
        allowed = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        ext = ext.lower() if ext.lower() in allowed else ""
        return f"{safe_stem}{ext}"

    @staticmethod
    def _dedupe_filename(name: str, existing: set[str]) -> str:
        if name not in existing:
            return name
        stem, ext = os.path.splitext(name)
        idx = 1
        while f"{stem}_{idx}{ext}" in existing:
            idx += 1
        return f"{stem}_{idx}{ext}"
