"""Smoke tests: the plugin module can be imported and has the expected shape."""

from __future__ import annotations

import importlib


def test_plugin_module_importable():
    """The top-level package import does not raise."""
    mod = importlib.import_module("astrbot_plugin_randommeme")
    assert mod is not None


def test_main_module_importable():
    mod = importlib.import_module("astrbot_plugin_randommeme.main")
    assert hasattr(mod, "RandomMemePlugin")


def test_manager_importable():
    from astrbot_plugin_randommeme.core import manager

    assert hasattr(manager, "MemeManager")


def test_register_decorator_is_identity():
    """The stubbed ``register`` decorator should not alter the class."""
    from astrbot_plugin_randommeme.main import RandomMemePlugin

    cls = RandomMemePlugin
    assert cls.__name__ == "RandomMemePlugin"


def test_metadata_yaml_minimum_fields():
    """Quick check that the metadata file has required keys."""
    from pathlib import Path

    import yaml

    metadata_path = Path(__file__).resolve().parents[1] / "metadata.yaml"
    data = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    for key in ("name", "desc", "version", "author"):
        assert key in data, f"metadata.yaml missing key: {key}"


def test_conf_schema_parses():
    import json
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for key, item in data.items():
        assert "type" in item, f"{key} missing type"


def test_plugin_page_layout_exists():
    """The plugin-page directory follows the conventions from
    ``docs/zh/dev/star/guides/plugin-pages.md``."""
    from pathlib import Path

    plugin_root = Path(__file__).resolve().parents[1]
    index = plugin_root / "pages" / "manager" / "index.html"
    assert index.exists(), f"missing: {index}"
    app = plugin_root / "pages" / "manager" / "app.js"
    assert app.exists(), f"missing: {app}"
    assert (plugin_root / "pages" / "manager" / "style.css").exists()
