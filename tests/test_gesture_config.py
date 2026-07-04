import os
import tempfile
import pytest
from pc_gesture.config import (
    DEFAULT_BINDINGS, GESTURES, ACTIONS,
    load_gesture_config, save_gesture_config,
)


def test_default_bindings_keys_are_all_gestures():
    assert set(DEFAULT_BINDINGS.keys()) == set(GESTURES)
    for v in DEFAULT_BINDINGS.values():
        assert v is None or v in ACTIONS


def test_set_and_get_binding():
    cfg = load_gesture_config()
    cfg.set_binding("FIST", "NEXT_PAGE")
    assert cfg.get_binding("FIST") == "NEXT_PAGE"
    cfg.set_binding("PALM", None)
    assert cfg.get_binding("PALM") is None


def test_set_binding_invalid_gesture_raises():
    cfg = load_gesture_config()
    with pytest.raises(ValueError):
        cfg.set_binding("BOGUS", "NEXT_PAGE")


def test_set_binding_invalid_action_raises():
    cfg = load_gesture_config()
    with pytest.raises(ValueError):
        cfg.set_binding("FIST", "BOGUS")


def test_reset_bindings_restores_defaults():
    cfg = load_gesture_config()
    cfg.set_binding("FIST", "EXIT")
    cfg.reset_bindings()
    assert cfg.get_binding("FIST") == DEFAULT_BINDINGS["FIST"]


def test_export_and_import_roundtrip():
    cfg = load_gesture_config()
    cfg.set_binding("FIST", "OPEN_PPT")
    data = cfg.export_dict()
    cfg2 = load_gesture_config()
    cfg2.import_dict(data)
    assert cfg2.get_binding("FIST") == "OPEN_PPT"


def test_import_drops_invalid_gesture_and_action():
    cfg = load_gesture_config()
    cfg.import_dict({"BOGUS": "NEXT_PAGE", "FIST": "BOGUS_ACTION"})
    assert "BOGUS" not in cfg.bindings
    assert cfg.get_binding("FIST") is None


def test_save_load_preserves_bindings():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "g.json")
        cfg = load_gesture_config(path=path)
        cfg.set_binding("FIST", "SCREENSHOT")
        save_gesture_config(cfg, path=path)
        cfg2 = load_gesture_config(path=path)
        assert cfg2.get_binding("FIST") == "SCREENSHOT"