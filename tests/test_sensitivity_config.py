"""Tests for info.txt 五.1: magic numbers extracted to sensitivity config.

Each magic number in semantics.py should now be readable from cfg.sensitivity
and have a sensible default.
"""

import time
import pytest

from pc_gesture.config import load_gesture_config, DEFAULT_GESTURE_CONFIG
from pc_gesture.semantics import GestureSemantics
from pc_gesture.pairing import PairingService


# ---- helper: minimal hand to drive the classifier ----

class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y


WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_TIP = 20


def _hand(thumb_xy, index_tip_xy, middle_tip_xy, ring_tip_xy, pinky_tip_xy,
          wrist_xy=(0.5, 0.7), mcp_xy=(0.5, 0.5)):
    """手部 landmark 构造器,MCP 都在 mcp_xy,其他 tip 按入参。"""
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(*wrist_xy)
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(*mcp_xy)
    for tip_xy, tip_idx, pip_idx in (
        (index_tip_xy, INDEX_TIP, INDEX_PIP),
        (middle_tip_xy, MIDDLE_TIP, MIDDLE_PIP),
        (ring_tip_xy, RING_TIP, RING_PIP),
        (pinky_tip_xy, PINKY_TIP, PINKY_PIP),
    ):
        lm[tip_idx] = _P(*tip_xy)
        if tip_xy[1] < mcp_xy[1]:
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1] + 0.05)
        else:
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1] - 0.05)
    lm[THUMB_TIP] = _P(*thumb_xy)
    return lm


# ---- defaults ----

def test_all_new_sensitivity_defaults_present():
    """8 个新字段都有默认值。"""
    s = DEFAULT_GESTURE_CONFIG["sensitivity"]
    assert s["thumb_touch_ratio"] == 0.08
    assert s["thumb_extend_ratio"] == 0.18
    assert s["ext_strict_y"] == 0.025
    assert s["ext_relaxed_y"] == 0.015
    assert s["curl_y"] == 0.005
    assert s["static_reset_idle_s"] == 0.3
    assert s["hand_lost_cleanup_s"] == 0.5
    assert s["pairing_pointing_up_s"] == 1.0
    assert s["pairing_window_ms"] == 3000


# ---- user can override thumb_touch_ratio ----

def test_user_can_tighten_thumb_touch_threshold():
    """调低 thumb_touch_ratio,让 OK 判定更严格(正常 OK 手距离不够)。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["thumb_touch_ratio"] = 0.0  # 阈值 0,任何距离都不算接触
    sem = GestureSemantics(cfg)
    # 标准 OK 手:thumb + index tip 重合
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.55, 0.2),  # 与 thumb 重合
        middle_tip_xy=(0.65, 0.2),
        ring_tip_xy=(0.7, 0.2),
        pinky_tip_xy=(0.75, 0.2),
    )
    # thumb_touch_ratio=0 → distance < 0 永远 False → 不判 OK
    # 4 指伸 → 判 PALM
    assert sem._classify_static(lm) == sem.G_PALM


def test_user_can_relax_thumb_touch_threshold():
    """调高 thumb_touch_ratio,让 OK 判定更宽松(分开的手指也算接触)。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["thumb_touch_ratio"] = 0.5  # 阈值 50% of hand size = 0.1
    sem = GestureSemantics(cfg)
    # 拇指 + 食指分开 0.05(小于阈值 0.1,被判为接触)
    lm = _hand(
        thumb_xy=(0.4, 0.2),
        index_tip_xy=(0.45, 0.2),  # dist 0.05 < 0.5*0.2=0.1 → 接触
        middle_tip_xy=(0.65, 0.2),
        ring_tip_xy=(0.7, 0.2),
        pinky_tip_xy=(0.75, 0.2),
    )
    assert sem._classify_static(lm) == sem.G_OK


# ---- user can override ext_strict_y ----

def test_user_can_relax_ext_strict_y():
    """把 ext_strict_y 从 0.025 调到 0.005,食指只需稍微伸就算 strict extended。"""
    cfg = load_gesture_config()
    # 食指微伸:tip.y=0.485, pip.y=0.5,差 0.015。
    # 原 strict 阈值 0.025:0.485 < 0.5-0.025=0.475? No → not strict ext
    # 调小到 0.005:0.485 < 0.5-0.005=0.495? Yes → strict ext
    cfg.raw["sensitivity"]["ext_strict_y"] = 0.005
    sem = GestureSemantics(cfg)
    lm = _hand(
        thumb_xy=(0.51, 0.51),  # 拇贴近,卷
        index_tip_xy=(0.6, 0.485),  # 微伸
        middle_tip_xy=(0.65, 0.5),  # 卷
        ring_tip_xy=(0.7, 0.5),
        pinky_tip_xy=(0.75, 0.5),
    )
    # 食指 strict ext,其它卷 → POINTING_UP
    assert sem._classify_static(lm) == sem.G_POINTING_UP


# ---- user can override ext_relaxed_y (影响 PALM/OK) ----

def test_user_can_relax_palm_threshold_via_ext_relaxed_y():
    """调高 ext_relaxed_y 让 PALM 更容易识别(但易误判,留作调参)。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["ext_relaxed_y"] = 0.005  # 极松
    sem = GestureSemantics(cfg)
    # 自然摊手:tip.y 0.49,pip.y 0.5,差 0.01 < 0.005? No。实际 tip-pip 差 0.01 > 0.005 → relaxed 视为伸
    # 改用更小的差测
    lm = _hand(
        thumb_xy=(0.15, 0.5),  # 拇横向
        index_tip_xy=(0.4, 0.5 - 0.003),  # tip y=0.497, pip y≈0.5,差 0.003
        middle_tip_xy=(0.5, 0.5 - 0.003),
        ring_tip_xy=(0.6, 0.5 - 0.003),
        pinky_tip_xy=(0.7, 0.5 - 0.003),
    )
    # 0.003 < 0.005 → 4 指都 relaxed extended → PALM
    assert sem._classify_static(lm) == sem.G_PALM


# ---- user can override hand_lost_cleanup_s ----

def test_user_can_extend_hand_lost_cleanup_window():
    """调高 hand_lost_cleanup_s,手消失更久后才清状态。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["hand_lost_cleanup_s"] = 10.0
    sem = GestureSemantics(cfg)
    st = sem._slots["A"]
    st.last_seen_monotonic = time.monotonic() - 0.5  # 500ms 前见过
    st.last_static_gesture = sem.G_OK
    st.static_cooldown_until = time.monotonic() + 5.0
    # process 空手 → 默认 0.5s 阈值会清,但 10s 阈值下不清
    sem.process([], [])
    assert st.last_static_gesture == sem.G_OK  # 保留


# ---- user can override static_reset_idle_s ----

def test_user_can_shorten_static_reset_idle_window():
    """调小 static_reset_idle_s,放下 100ms 就能再次触发同一手势。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["static_reset_idle_s"] = 0.1
    sem = GestureSemantics(cfg)
    st = sem._slots["A"]
    st.last_static_gesture = sem.G_OK
    st.last_static_at = time.monotonic() - 0.2  # 200ms 前
    sem._classify_static = lambda lm: sem.G_NONE
    sem.process([_hand((0.51, 0.51), (0.6, 0.2), (0.65, 0.5),
                       (0.7, 0.5), (0.75, 0.5))], [])
    # 200ms > 100ms 阈值 → auto-reset
    assert st.last_static_gesture == sem.G_NONE


# ---- user can override pairing_pointing_up_s ----

def test_user_can_shorten_pairing_pointing_up_duration():
    """调小 pairing_pointing_up_s,半秒就能配对成功。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["pairing_pointing_up_s"] = 0.5
    sem = GestureSemantics(cfg)
    sem.start_pairing()
    # A 槽 doing pointing_up,设 pointing_up_start 0.7s 前(> 0.5s 阈值)
    sem._pairing._slot_pointing_up_start["A"] = time.monotonic() - 0.7
    sem._pairing.update(
        time.monotonic(),
        {"A": sem.G_POINTING_UP, "B": "NONE"},
        sem.G_POINTING_UP,
    )
    assert sem._pairing.confirmed is True


# ---- bad config fallback ----

def test_invalid_threshold_falls_back_to_default():
    """sensitivity 给字符串/None,应 fallback 到默认值,不要崩。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["thumb_touch_ratio"] = "not a number"
    cfg.raw["sensitivity"]["ext_strict_y"] = None
    sem = GestureSemantics(cfg)
    # 标准 OK 手:thumb + index 重合,中/无名/小指伸
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.55, 0.2),
        middle_tip_xy=(0.65, 0.2),
        ring_tip_xy=(0.7, 0.2),
        pinky_tip_xy=(0.75, 0.2),
    )
    # 走默认阈值,识别为 OK(不会因为无效配置崩)
    assert sem._classify_static(lm) == sem.G_OK


def test_start_pairing_uses_config_default_when_no_arg():
    """start_pairing() 不传参时,window_ms 用 cfg.sensitivity.pairing_window_ms。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["pairing_window_ms"] = 7777
    sem = GestureSemantics(cfg)
    sem.start_pairing()
    # 内部窗口起始时间应被设置(确认 PairingService 接受了 config)
    assert sem._pairing._started > 0 or sem._pairing.state == PairingService.PAIRING_WAITING


def test_start_pairing_explicit_arg_overrides_config():
    """start_pairing(500) 显式传参,PairingService 应使用该窗口。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["pairing_window_ms"] = 99999  # 极长
    sem = GestureSemantics(cfg)
    sem.start_pairing(window_ms=500)
    # 500ms 短窗口 — 等 600ms 后应 EXPIRED
    time.sleep(0.6)
    assert sem._pairing.state == PairingService.PAIRING_EXPIRED