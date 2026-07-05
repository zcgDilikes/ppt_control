import json
import os
import tempfile

from pc_gesture.config import load_gesture_config, save_gesture_config


def test_tutorial_done_defaults_false():
    cfg = load_gesture_config()
    assert cfg.tutorial_done is False


def test_tutorial_done_round_trips(tmp_path):
    cfg = load_gesture_config()
    cfg.tutorial_done = True
    p = tmp_path / "gesture_cfg.json"
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert cfg2.tutorial_done is True


def test_tutorial_done_missing_in_old_config_is_backfilled(tmp_path):
    """旧配置文件没有 tutorial_done 字段时,_merge_defaults 必须补默认值 False。"""
    p = tmp_path / "old_cfg.json"
    p.write_text(json.dumps({"operator_mode": "single"}), encoding="utf-8")
    cfg = load_gesture_config(str(p))
    assert cfg.tutorial_done is False