"""Tests for ppt_core.settings."""

import json
from pathlib import Path

import pytest

from ppt_core.settings import (
    DEFAULT_SETTINGS,
    load_settings,
    save_settings,
)


def test_load_missing_returns_defaults(tmp_path: Path):
    """Nonexistent file returns DEFAULT_SETTINGS dict."""
    settings_path = tmp_path / "settings.json"
    assert not settings_path.exists()

    result = load_settings(path=settings_path)

    assert result == DEFAULT_SETTINGS


def test_save_then_load_roundtrip(tmp_path: Path):
    """Save then load returns an equal dict."""
    settings_path = tmp_path / "settings.json"
    payload = {
        "screenshot_open_folder": False,
        "transfer_open_folder": False,
        "transfer_open_ppt": True,
        "ppt_notes_enabled": True,
        "open_ppt_path": "C:/some/path.pptx",
    }

    save_settings(payload, path=settings_path)
    result = load_settings(path=settings_path)

    assert result == payload


def test_load_partial_merges_defaults(tmp_path: Path):
    """Partial user file: missing keys fall back to defaults."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"screenshot_open_folder": False}), encoding="utf-8")

    result = load_settings(path=settings_path)

    assert result["screenshot_open_folder"] is False
    # All other keys come from defaults
    assert result["transfer_open_folder"] == DEFAULT_SETTINGS["transfer_open_folder"]
    assert result["transfer_open_ppt"] == DEFAULT_SETTINGS["transfer_open_ppt"]
    assert result["ppt_notes_enabled"] == DEFAULT_SETTINGS["ppt_notes_enabled"]
    assert result["open_ppt_path"] == DEFAULT_SETTINGS["open_ppt_path"]


def test_load_corrupt_returns_defaults(tmp_path: Path):
    """Corrupt JSON returns defaults rather than raising."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not valid json,,,", encoding="utf-8")

    result = load_settings(path=settings_path)

    assert result == DEFAULT_SETTINGS


def test_save_creates_dirs(tmp_path: Path):
    """Save to a nested non-existent directory succeeds and creates the dir."""
    nested_path = tmp_path / "a" / "b" / "c" / "settings.json"
    assert not nested_path.parent.exists()

    save_settings(DEFAULT_SETTINGS, path=nested_path)

    assert nested_path.exists()
    assert nested_path.parent.is_dir()
    # And it's parseable as JSON with our defaults
    assert json.loads(nested_path.read_text(encoding="utf-8")) == DEFAULT_SETTINGS
