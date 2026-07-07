"""Tests for 9-event gesture system (info.txt 9-events design)."""
from pc_gesture.config import (
    DEFAULT_GESTURE_CONFIG,
    DEFAULT_TIP_BINDINGS,
    TIP_GESTURES,
    GestureConfig,
)


def test_tip_gestures_enum_has_nine():
    """9 个事件: 4 × 2 + 1 interlock"""
    assert len(TIP_GESTURES) == 9
    assert "L_HAND_INDEX" in TIP_GESTURES
    assert "L_HAND_MIDDLE" in TIP_GESTURES
    assert "L_HAND_RING" in TIP_GESTURES
    assert "L_HAND_PINKY" in TIP_GESTURES
    assert "R_HAND_INDEX" in TIP_GESTURES
    assert "R_HAND_MIDDLE" in TIP_GESTURES
    assert "R_HAND_RING" in TIP_GESTURES
    assert "R_HAND_PINKY" in TIP_GESTURES
    assert "HANDS_INTERLOCK" in TIP_GESTURES


def test_default_tip_bindings_have_all_nine():
    """每个 tip 事件都有默认 binding(可能 None)"""
    assert len(DEFAULT_TIP_BINDINGS) == 9
    for g in TIP_GESTURES:
        assert g in DEFAULT_TIP_BINDINGS
        v = DEFAULT_TIP_BINDINGS[g]
        assert v is None or isinstance(v, str)


def test_sensitivity_has_new_fields():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    s = cfg.sensitivity
    assert s["tip_touch_ratio"] == 0.55
    assert s["interlock_max_wrist_dist"] == 0.20
    assert s["interlock_max_tip_dist"] == 0.40
    assert s["interlock_min_dwell_s"] == 0.3


def test_tip_bindings_attribute_round_trip():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    # 读默认
    assert cfg.tip_bindings["L_HAND_INDEX"] == "NEXT_PAGE"
    # 改
    cfg.set_tip_binding("L_HAND_INDEX", "BLACK_SCREEN")
    assert cfg.get_tip_binding("L_HAND_INDEX") == "BLACK_SCREEN"
    # 写盘
    cfg.set_tip_binding("L_HAND_MIDDLE", None)
    assert cfg.get_tip_binding("L_HAND_MIDDLE") is None


def test_set_tip_binding_rejects_unknown_gesture():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("UNKNOWN_GESTURE", "NEXT_PAGE")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")


def test_set_tip_binding_rejects_unknown_action():
    cfg = GestureConfig(raw=dict(DEFAULT_GESTURE_CONFIG))
    try:
        cfg.set_tip_binding("L_HAND_INDEX", "FAKE_ACTION")
    except ValueError:
        return
    raise AssertionError("should have raised ValueError")