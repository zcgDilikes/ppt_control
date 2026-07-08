"""Tests for 9-event sensitivity config (after 7-gesture removal).

7 旧 gesture 相关 sensitivity 已删,只保留 9-event + 公共配置。
"""
import pytest

from pc_gesture.config import (
    GestureConfig,
    load_gesture_config,
)


def test_all_new_sensitivity_defaults_present():
    """9-event 用的 4 个 sensitivity 必须存在,默认值正确"""
    cfg = load_gesture_config()
    s = cfg.sensitivity
    assert s["tip_touch_ratio"] == 0.55
    assert s["interlock_max_wrist_dist"] == 0.20
    assert s["interlock_max_tip_dist"] == 0.40
    assert s["interlock_min_dwell_s"] == 2.0  # P0.2:调高到 2s 防误触
    # 公共配置
    assert s["low_confidence_threshold"] == 0.6
    assert s["hand_lost_cleanup_s"] == 0.5
    assert s["debug_log"] is False
    assert s["laser_smoothing"] == 0.55
    assert s["pinch_threshold"] == 0.32
    assert s["pinch_release"] == 0.45
    assert s["gesture_cooldown_ms"] == 400


def test_user_can_tighten_tip_touch_threshold():
    """调小 tip_touch_ratio 让更宽松接触也能识别"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["tip_touch_ratio"] = 1.0
    assert cfg.sensitivity["tip_touch_ratio"] == 1.0


def test_user_can_relax_tip_touch_threshold():
    """调大 tip_touch_ratio 让更严格接触才识别"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["tip_touch_ratio"] = 0.2
    assert cfg.sensitivity["tip_touch_ratio"] == 0.2


def test_user_can_extend_hand_lost_cleanup_window():
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["hand_lost_cleanup_s"] = 2.0
    assert cfg.sensitivity["hand_lost_cleanup_s"] == 2.0


def test_user_can_shorten_interlock_dwell():
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["interlock_min_dwell_s"] = 0.1
    assert cfg.sensitivity["interlock_min_dwell_s"] == 0.1


def test_invalid_threshold_does_not_crash():
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["tip_touch_ratio"] = "not a number"
    # 不抛异常,_detect_tip_touches fallback 到默认值
    from pc_gesture.semantics import GestureSemantics
    from pc_gesture.semantics import WRIST, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP, THUMB_TIP
    sem = GestureSemantics(cfg)
    lm = [_P(0.5, 0.5) for _ in range(21)]
    lm[0] = _P(0.3, 0.7)
    lm[5] = _P(0.3, 0.5)
    # 不应该 raise
    result = sem._detect_tip_touches(lm, "A")
    assert result == "NONE" or result in (
        "L_HAND_INDEX", "L_HAND_MIDDLE", "L_HAND_RING", "L_HAND_PINKY",
    )


class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y
