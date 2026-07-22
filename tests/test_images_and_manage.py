"""Tests for chat image extract helpers and manage permission helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from astrbot_plugin_randommeme.core.images import (
    collect_image_components,
    extract_image_uploads,
)
from astrbot_plugin_randommeme.main import HELP_TEXT, RandomMemePlugin, _split_tokens


def test_split_tokens():
    assert _split_tokens("摸鱼 moyu 摸一下") == ["摸鱼", "moyu", "摸一下"]
    assert _split_tokens("  ") == []
    assert _split_tokens(None) == []


def test_help_text_has_short_commands():
    for phrase in ("表情 列表", "表情 加", "表情 新", "表情 别名", "表情 帮助"):
        assert phrase in HELP_TEXT


def test_collect_image_components_includes_reply_chain():
    class Image:
        def __init__(self, path: str):
            self.path = path
            self.url = ""
            self.file = path

        async def convert_to_file_path(self) -> str:
            return self.path

    class Reply:
        def __init__(self, chain):
            self.chain = chain
            self.id = "1"

    img = Image("/tmp/a.jpg")
    event = SimpleNamespace(
        get_messages=lambda: [Reply([img]), SimpleNamespace(text="x")],
        message_obj=None,
    )
    comps = collect_image_components(event)
    assert len(comps) == 1
    assert comps[0] is img


@pytest.mark.asyncio
async def test_extract_image_uploads_reads_file(tmp_path):
    img_path = tmp_path / "x.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    class Image:
        def __init__(self, path: str):
            self.path = path
            self.url = ""
            self.file = path

        async def convert_to_file_path(self) -> str:
            return self.path

    event = SimpleNamespace(
        get_messages=lambda: [Image(str(img_path))],
        message_obj=None,
    )
    uploads = await extract_image_uploads(event)
    assert len(uploads) == 1
    name, content = uploads[0]
    assert name.endswith(".png")
    assert content.startswith(b"\x89PNG")


def _make_plugin(conf: dict) -> RandomMemePlugin:
    ctx = SimpleNamespace(register_web_api=lambda *a, **k: None)
    plugin = RandomMemePlugin(ctx, conf)  # type: ignore[arg-type]
    return plugin


@pytest.mark.asyncio
async def test_admin_only_manage_gate(isolated_plugin_data):
    conf = {
        "gif_support": True,
        "exact_match": False,
        "admin_only_manage": True,
    }
    plugin = _make_plugin(conf)
    await plugin.manager.load()

    admin_event = SimpleNamespace(is_admin=lambda: True)
    user_event = SimpleNamespace(is_admin=lambda: False)
    assert plugin._manage_allowed(admin_event) is True
    assert plugin._manage_allowed(user_event) is False

    conf["admin_only_manage"] = False
    plugin.conf = conf
    assert plugin._manage_allowed(user_event) is True


@pytest.mark.asyncio
async def test_cmd_new_and_alias_flow(isolated_plugin_data):
    conf = {"gif_support": True, "admin_only_manage": False}
    plugin = _make_plugin(conf)
    await plugin.manager.load()

    event = SimpleNamespace(
        plain_result=lambda s: s,
        is_admin=lambda: True,
    )

    results = []
    async for r in plugin.cmd_new(event, "摸鱼 moyu"):
        results.append(r)
    assert any("已创建" in str(x) for x in results)
    assert plugin.manager.get_group("摸鱼") is not None
    assert plugin.manager.match_group("moyu").name == "摸鱼"

    results = []
    async for r in plugin.cmd_aliases(event, "摸鱼 摸鱼一下"):
        results.append(r)
    g = plugin.manager.get_group("摸鱼")
    assert g is not None
    assert g.aliases == ["摸鱼一下"]
