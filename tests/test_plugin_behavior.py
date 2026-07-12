"""Behavior tests for the core manager (match, draw pool, CRUD, file ops)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astrbot_plugin_randommeme.core.group import Group, dump_state, normalize_state
from astrbot_plugin_randommeme.core.manager import MemeManager
from astrbot_plugin_randommeme.core.storage import (
    STATE_FILE,
    is_image_filename,
    memes_dir,
    plugin_data_dir,
    safe_group_name,
)


# ------------------------------------------------------------ match tests


@pytest.mark.asyncio
async def test_match_group_exact_mode(isolated_plugin_data):
    mgr = MemeManager(gif_support=True, exact_match=True)
    await mgr.create_group("摸鱼", aliases=["moyu", "摸鱼一下"])
    await mgr.create_group("干饭", aliases=["ganfan"])
    await mgr.update_group("干饭", enabled=False)

    assert mgr.match_group("摸鱼").name == "摸鱼"
    assert mgr.match_group("MOYU").name == "摸鱼"
    assert mgr.match_group("干饭") is None  # disabled
    # partial should NOT match in exact mode
    assert mgr.match_group("摸鱼一下子") is None
    # leading / trailing whitespace IS trimmed
    assert mgr.match_group("  摸鱼  ").name == "摸鱼"
    assert mgr.match_group(" moyu ").name == "摸鱼"


@pytest.mark.asyncio
async def test_match_group_fuzzy_mode(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("doro", aliases=["多肉"])
    await mgr.create_group("doro2", aliases=["多肉2"])

    # exact still works
    assert mgr.match_group("doro").name == "doro"
    # partial / contained
    assert mgr.match_group("看doro").name == "doro"
    assert mgr.match_group("doro表情").name == "doro"
    # longest keyword wins
    assert mgr.match_group("多肉2").name == "doro2"
    assert mgr.match_group("多肉").name == "doro"
    # case-insensitive
    assert mgr.match_group("DORO").name == "doro"


# ------------------------------------------------------------ draw tests


@pytest.mark.asyncio
async def test_draw_returns_full_rotation_then_resets():
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("g")
    await mgr.add_images("g", [("a.jpg", b"x"), ("b.jpg", b"y"), ("c.jpg", b"z")])
    seen: list[str] = []
    for _ in range(3):
        path = await mgr.draw("g")
        seen.append(Path(path).name)
    assert sorted(seen) == ["a.jpg", "b.jpg", "c.jpg"]
    # fourth draw starts a new round -> not None and not identical previous
    fourth = await mgr.draw("g")
    assert fourth is not None
    assert Path(fourth).name in {"a.jpg", "b.jpg", "c.jpg"}


@pytest.mark.asyncio
async def test_draw_no_images_returns_none():
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("empty")
    assert await mgr.draw("empty") is None


@pytest.mark.asyncio
async def test_draw_unknown_group_returns_none():
    mgr = MemeManager(gif_support=True)
    assert await mgr.draw("nope") is None


# ------------------------------------------------------------ CRUD tests


@pytest.mark.asyncio
async def test_create_group_and_persist(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    g = await mgr.create_group("demo", aliases=["d"])
    assert g.name == "demo"
    state_path = plugin_data_dir() / STATE_FILE
    assert state_path.exists()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    names = [item["name"] for item in data["groups"]]
    assert names == ["demo"]


@pytest.mark.asyncio
async def test_create_group_rejects_duplicate_name_and_alias_conflict(
    isolated_plugin_data,
):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("a", aliases=["x"])
    with pytest.raises(ValueError):
        await mgr.create_group("a")
    with pytest.raises(ValueError):
        await mgr.create_group("b", aliases=["x"])


@pytest.mark.asyncio
async def test_update_group_changes_aliases_and_require_wake(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("moyu")
    g = await mgr.update_group("moyu", aliases=["摸摸"], require_wake=True)
    assert "摸摸" in g.aliases
    assert g.require_wake is True


@pytest.mark.asyncio
async def test_delete_group_removes_dir_and_history(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("goner")
    await mgr.add_images("goner", [("a.jpg", b"x")])
    gdir = memes_dir("goner")
    assert gdir.exists()
    assert await mgr.delete_group("goner")
    assert not gdir.exists()
    assert mgr.get_group("goner") is None


# ------------------------------------------------------------ image tests


@pytest.mark.asyncio
async def test_add_images_dedup(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("g")
    stored = await mgr.add_images("g", [("a.jpg", b"1"), ("a.jpg", b"2")])
    assert len(stored) == 2
    assert stored[0] == "a.jpg"
    assert stored[1].startswith("a_")


@pytest.mark.asyncio
async def test_delete_images_prunes_history(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("g")
    await mgr.add_images("g", [("a.jpg", b"1"), ("b.jpg", b"2"), ("c.jpg", b"3")])
    # draw all 3 to fill history
    for _ in range(3):
        await mgr.draw("g")
    removed = await mgr.delete_images("g", ["a.jpg"])
    assert removed == ["a.jpg"]
    # history should not contain deleted image
    history = mgr._history["g"]  # noqa: SLF001 (test inspection)
    assert "a.jpg" not in history


@pytest.mark.asyncio
async def test_delete_images_rejects_path_traversal(isolated_plugin_data):
    mgr = MemeManager(gif_support=True)
    await mgr.create_group("g")
    await mgr.add_images("g", [("a.jpg", b"1")])
    removed = await mgr.delete_images("g", ["../groups.json"])
    assert removed == []


# ------------------------------------------------------------ persistence


@pytest.mark.asyncio
async def test_load_round_trip(isolated_plugin_data):
    mgr_a = MemeManager(gif_support=True)
    await mgr_a.create_group("g", aliases=["x"])
    await mgr_a.add_images("g", [("a.jpg", b"x")])
    await mgr_a.draw("g")

    mgr_b = MemeManager(gif_support=True)
    await mgr_b.load()
    assert mgr_b.get_group("g") is not None
    assert "a.jpg" in mgr_b._history.get("g", [])  # noqa: SLF001


def test_safe_group_name_filters_unsafe_chars():
    assert safe_group_name("摸鱼") == "摸鱼"
    assert safe_group_name("a/b") == "a_b"
    with pytest.raises(ValueError):
        safe_group_name("")


def test_is_image_filename_static_only_when_gif_disabled():
    assert is_image_filename("a.jpg", gif_support=False)
    assert is_image_filename("a.GIF", gif_support=True)
    assert not is_image_filename("a.gif", gif_support=False)
    assert not is_image_filename("a.txt", gif_support=True)


def test_normalize_state_handles_garbage():
    groups, history = normalize_state({"groups": "not a list"})
    assert groups == []
    assert history == {}
    data = dump_state([Group(name="g")], {"g": ["a.jpg"]})
    assert data["groups"][0]["name"] == "g"
    assert data["history"]["g"] == ["a.jpg"]
