"""Tests for sensitivity.low_confidence_threshold default + round-trip."""

import json

from pc_gesture.config import load_gesture_config, save_gesture_config


def test_low_confidence_threshold_default():
    cfg = load_gesture_config()
    assert cfg.sensitivity.get("low_confidence_threshold") == 0.6


def test_low_confidence_threshold_round_trips(tmp_path):
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["low_confidence_threshold"] = 0.75
    p = tmp_path / "g.json"
    save_gesture_config(cfg, str(p))
    cfg2 = load_gesture_config(str(p))
    assert cfg2.sensitivity["low_confidence_threshold"] == 0.75


def test_low_confidence_threshold_missing_in_old_config_is_backfilled(tmp_path):
    """旧 sensitivity 字典缺字段时,_merge_defaults 必须补默认值。"""
    p = tmp_path / "old.json"
    p.write_text(
        json.dumps({"sensitivity": {"swipe_min_velocity": 0.2}}),
        encoding="utf-8",
    )
    cfg = load_gesture_config(str(p))
    assert cfg.sensitivity["low_confidence_threshold"] == 0.6
    # 旧字段也保留
    assert cfg.sensitivity["swipe_min_velocity"] == 0.2