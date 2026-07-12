"""组别数据模型与序列化。

单一数据来源：``groups.json``，结构：

.. code-block:: json

    {
        "groups": [
            {
                "name": "摸鱼",
                "aliases": ["moyu", "摸鱼一下"],
                "require_wake": false,
                "enabled": true,
                "created_at": 1700000000
            }
        ],
        "history": {
            "摸鱼": ["a.jpg", "b.png"]
        }
    }
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Group:
    """A meme group definition."""

    name: str
    aliases: list[str] = field(default_factory=list)
    require_wake: bool = False
    enabled: bool = True
    created_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Group":
        raw_aliases = data.get("aliases") or []
        if not isinstance(raw_aliases, list):
            raw_aliases = []
        return cls(
            name=str(data.get("name") or "").strip(),
            aliases=[str(a).strip() for a in raw_aliases if str(a).strip()],
            require_wake=bool(data.get("require_wake", False)),
            enabled=bool(data.get("enabled", True)),
            created_at=float(data.get("created_at") or time.time()),
        )

    def all_keywords(self) -> list[str]:
        """All trigger keywords (name + aliases), each non-empty after strip."""
        return [str(a).strip() for a in [self.name, *self.aliases] if str(a).strip()]


def normalize_state(data: Any) -> tuple[list[Group], dict[str, list[str]]]:
    """Normalize raw JSON state into ``(groups, history)`` pair.

    Args:
        data: Anything previously loaded from ``groups.json`` (or a fresh dict).

    Returns:
        A 2-tuple ``(groups, history)`` where ``history`` maps group name to the
        ordered list of filenames already drawn in the current round.
    """
    if not isinstance(data, dict):
        data = {}
    raw_groups = data.get("groups") or []
    if not isinstance(raw_groups, list):
        raw_groups = []
    groups = [Group.from_dict(g) for g in raw_groups if isinstance(g, dict)]
    groups = [g for g in groups if g.name]

    raw_history = data.get("history") or {}
    if not isinstance(raw_history, dict):
        raw_history = {}
    history: dict[str, list[str]] = {}
    for key, value in raw_history.items():
        if not isinstance(value, list):
            continue
        history[str(key)] = [str(x) for x in value if isinstance(x, str)]

    return groups, history


def dump_state(groups: list[Group], history: dict[str, list[str]]) -> dict[str, Any]:
    """Serialize ``groups``/``history`` back to the on-disk JSON shape."""
    return {
        "groups": [g.to_dict() for g in groups],
        "history": history,
    }
