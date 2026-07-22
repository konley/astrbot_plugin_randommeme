"""Pytest conftest: stub the minimal ``astrbot`` surface used by this plugin.

We do not assume a running AstrBot install. The stubs are intentionally
shallow; module logic that needs richer objects is exercised by behavior
tests using lightweight mocks.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# Make ``from astrbot_plugin_randommeme.core...`` importable when pytest runs
# from inside the plugin directory. The folder *containing* this plugin must
# be on ``sys.path`` so the plugin package can be resolved by name.
# parents[0] = tests/, parents[1] = astrbot_plugin_randommeme/, parents[2] = repo root
_PARENT_OF_PLUGIN = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, _PARENT_OF_PLUGIN)


_ASTRBOT_STUB_INSTALLED = False


def _install_stubs() -> None:
    global _ASTRBOT_STUB_INSTALLED
    if _ASTRBOT_STUB_INSTALLED:
        return
    if "astrbot" in sys.modules and hasattr(sys.modules["astrbot"], "__is_stub__"):
        return

    def _passthrough(*args, **kwargs):
        def deco(fn):
            return fn

        return deco

    api_event = types.ModuleType("astrbot.api.event")
    def _command_group(*args, **kwargs):
        def deco(fn):
            # mimic RegisteringCommandable: allow @group.command(...)
            fn.command = _passthrough
            fn.group = _command_group
            fn.custom_filter = _passthrough
            return fn

        return deco

    api_event.filter = types.SimpleNamespace(
        command=_passthrough,
        command_group=_command_group,
        regex=_passthrough,
        on_llm_request=_passthrough,
        on_decorating_result=_passthrough,
        permission_type=_passthrough,
        platform_adapter_type=_passthrough,
        event_message_type=_passthrough,
    )
    api_event.AstrMessageEvent = object

    api_provider = types.ModuleType("astrbot.api.provider")
    api_provider.ProviderRequest = type("ProviderRequest", (), {"system_prompt": ""})

    api_star = types.ModuleType("astrbot.api.star")

    class _StarBase:
        def __init__(self, context=None, *args, **kwargs):
            self.context = context

    api_star.Star = _StarBase
    api_star.Context = object

    def _register(*args, **kwargs):
        def deco(cls):
            return cls

        return deco

    api_star.register = _register

    core = types.ModuleType("astrbot.core")

    class _AstrBotConfig(dict):
        def save_config(self) -> None:
            return None

    core.AstrBotConfig = _AstrBotConfig

    core_platform = types.ModuleType("astrbot.core.platform")

    class _AstrMessageEvent:  # placeholder
        is_at_or_wake_command: bool = False
        message_str: str = ""

    core_platform.AstrMessageEvent = _AstrMessageEvent

    core_message = types.ModuleType("astrbot.core.message")
    core_components = types.ModuleType("astrbot.core.message.components")
    core_components.Image = type(
        "Image",
        (),
        {
            "fromFileSystem": staticmethod(lambda p, **kw: ("ImageFS", p)),
            "fromBytes": staticmethod(lambda b: ("ImageBytes", b)),
            "fromURL": staticmethod(lambda u, **kw: ("ImageURL", u)),
        },
    )
    class _StubReply:
        def __init__(self, **kw):
            self.id = kw.get("id", "")
        def toDict(self):
            return {"type": "reply", "data": {"id": str(self.id)}}
    core_components.Reply = _StubReply

    core_star_filter = types.ModuleType("astrbot.core.star.filter")
    event_message_type_mod = types.ModuleType(
        "astrbot.core.star.filter.event_message_type"
    )

    class _EventMessageType:
        ALL = "ALL"

    event_message_type_mod.EventMessageType = _EventMessageType

    core_utils = types.ModuleType("astrbot.core.utils")
    astrbot_path = types.ModuleType("astrbot.core.utils.astrbot_path")

    # real plugin-data path is computed lazily inside storage.py
    _plugin_data_state: dict[str, str | None] = {"dir": None}

    def _get_plugin_data_path() -> str:
        value = _plugin_data_state.get("dir")
        return value or ""

    astrbot_path.get_astrbot_plugin_data_path = _get_plugin_data_path

    core_star = types.ModuleType("astrbot.core.star")
    core_star_filter_pkg = types.ModuleType("astrbot.core.star.filter")
    command_mod = types.ModuleType("astrbot.core.star.filter.command")

    class _GreedyStr(str):
        """Stub of AstrBot GreedyStr marker."""

    command_mod.GreedyStr = _GreedyStr

    # Web API 层依赖 quart；测试不真正起 HTTP，仅 stub 模块
    if "quart" not in sys.modules:
        quart_mod = types.ModuleType("quart")
        quart_mod.jsonify = lambda *a, **k: a[0] if a else {}
        quart_mod.request = types.SimpleNamespace()
        quart_mod.send_file = lambda *a, **k: None
        sys.modules["quart"] = quart_mod

    api_pkg = types.ModuleType("astrbot.api")
    api_pkg.__is_stub__ = True
    sys.modules["astrbot"] = api_pkg
    sys.modules["astrbot.api"] = api_pkg
    sys.modules["astrbot.api.event"] = api_event
    sys.modules["astrbot.api.provider"] = api_provider
    sys.modules["astrbot.api.star"] = api_star
    sys.modules["astrbot.core"] = core
    sys.modules["astrbot.core.message"] = core_message
    sys.modules["astrbot.core.message.components"] = core_components
    sys.modules["astrbot.core.platform"] = core_platform
    sys.modules["astrbot.core.star"] = core_star
    sys.modules["astrbot.core.star.filter"] = core_star_filter_pkg
    sys.modules["astrbot.core.star.filter.event_message_type"] = event_message_type_mod
    sys.modules["astrbot.core.star.filter.command"] = command_mod
    sys.modules["astrbot.core.utils"] = core_utils
    sys.modules["astrbot.core.utils.astrbot_path"] = astrbot_path

    plugin_data_helper = types.ModuleType("astrbot_plugin_randommeme._conftest_helper")

    def _set_plugin_data_dir(path: str) -> None:
        _plugin_data_state["dir"] = path

    def _get_plugin_data_dir() -> str | None:
        return _plugin_data_state.get("dir")

    plugin_data_helper.set_dir = _set_plugin_data_dir
    plugin_data_helper.get_dir = _get_plugin_data_dir
    sys.modules["astrbot_plugin_randommeme._conftest_helper"] = plugin_data_helper

    _ASTRBOT_STUB_INSTALLED = True


# Install stubs as soon as the conftest is imported so that test-module
# collection has the same module surface as the test bodies do.
_install_stubs()


@pytest.fixture(autouse=True)
def isolated_plugin_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test gets its own ``get_astrbot_plugin_data_path`` that
    points at a freshly created temp directory."""
    _install_stubs()
    helper = sys.modules["astrbot_plugin_randommeme._conftest_helper"]
    helper.set_dir(str(tmp_path))
    yield tmp_path
    helper.set_dir("")
