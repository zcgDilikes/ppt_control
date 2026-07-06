"""Tests for GestureConfig.migrate_old_bindings — drops deprecated gesture keys."""

import json

from pc_gesture.config import load_gesture_config, save_gesture_config, GESTURES


def test_gestures_tuple_has_seven_new_entries():
    """新 GESTURES tuple 长度 7,包含全部新名,不含旧名。"""
    assert len(GESTURES) == 7
    expected = {"OK", "L_SIGN", "THREE_FINGERS", "POINTING_UP", "SCISSORS", "FIST", "PALM"}
    assert set(GESTURES) == expected
    assert "THUMBS_UP" not in GESTURES
    assert "SWIPE_LEFT" not in GESTURES


def test_migrate_returns_false_for_clean_config():
    cfg = load_gesture_config()
    cfg.tutorial_done = True  # ensure non-default
    migrated = cfg.migrate_old_bindings()
    assert migrated is False
    assert cfg.tutorial_done is True  # 未触动


def test_migrate_drops_thumbs_up(tmp_path):
    """旧 THUMBS_UP 键会被删除,tutorial_done 重置。"""
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({
        "bindings": {"THUMBS_UP": "FULL_SCREEN", "FIST": "BLACK_SCREEN"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.tutorial_done = True
    migrated = cfg.migrate_old_bindings()
    assert migrated is True
    assert "THUMBS_UP" not in cfg.raw.get("bindings", {})
    assert cfg.get_binding("FIST") == "BLACK_SCREEN"  # FIST 保留
    assert cfg.tutorial_done is False


def test_migrate_drops_all_deprecated_keys(tmp_path):
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({
        "bindings": {
            "THUMBS_UP": "FULL_SCREEN",
            "THUMBS_DOWN": "EXIT",
            "SWIPE_LEFT": "PREV_PAGE",
            "SWIPE_RIGHT": "NEXT_PAGE",
            "FIST": "BLACK_SCREEN",
        }
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    migrated = cfg.migrate_old_bindings()
    assert migrated is True
    deprecated = {"THUMBS_UP", "THUMBS_DOWN", "SWIPE_LEFT", "SWIPE_RIGHT"}
    assert not (set(cfg.raw.get("bindings", {}).keys()) & deprecated)
    assert cfg.get_binding("FIST") == "BLACK_SCREEN"


def test_migrate_returns_false_when_only_valid_keys_present(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "bindings": {"FIST": "BLACK_SCREEN", "PALM": "EXIT"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.tutorial_done = True
    migrated = cfg.migrate_old_bindings()
    assert migrated is False
    assert cfg.tutorial_done is True


def test_migrate_persists_changes_via_save(tmp_path):
    """迁移后再 save + reload,旧键不会回来。"""
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({
        "bindings": {"THUMBS_UP": "FULL_SCREEN"}
    }), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    cfg.migrate_old_bindings()
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert "THUMBS_UP" not in cfg2.raw.get("bindings", {})
    assert cfg2.tutorial_done is False
