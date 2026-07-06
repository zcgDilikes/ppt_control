"""Tests for info.txt Phase 6 — new event features: ts, gesture_end, MOUSE_DOWN/UP.

Phase 1-2: events have ts/ts_ms + GESTURE_END on release.
Phase 5: pinch emits MOUSE_DOWN on start, MOUSE_UP on release.
"""

import time
import pytest

from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


# ---- helpers ----

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


def _make_ok_hand():
    """OK 手势:thumb-index 接触,中/无名/小指伸。"""
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.3, 0.7)
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(0.3, 0.5)
    lm[INDEX_PIP] = _P(0.35, 0.22)
    lm[INDEX_TIP] = _P(0.35, 0.2)
    lm[MIDDLE_PIP] = _P(0.4, 0.22)
    lm[MIDDLE_TIP] = _P(0.4, 0.2)
    lm[RING_PIP] = _P(0.45, 0.22)
    lm[RING_TIP] = _P(0.45, 0.2)
    lm[PINKY_PIP] = _P(0.5, 0.22)
    lm[PINKY_TIP] = _P(0.5, 0.2)
    lm[THUMB_TIP] = _P(0.35, 0.2)
    return lm


def _make_pinch_hand():
    """捏合:thumb-index 极近,其他手指张开。"""
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.3, 0.7)
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(0.3, 0.5)
    # index tip 与 thumb tip 几乎重叠
    lm[INDEX_PIP] = _P(0.4, 0.22)
    lm[INDEX_TIP] = _P(0.4, 0.2)
    lm[MIDDLE_PIP] = _P(0.5, 0.22)
    lm[MIDDLE_TIP] = _P(0.5, 0.2)
    lm[RING_PIP] = _P(0.6, 0.22)
    lm[RING_TIP] = _P(0.6, 0.2)
    lm[PINKY_PIP] = _P(0.7, 0.22)
    lm[PINKY_TIP] = _P(0.7, 0.2)
    lm[THUMB_TIP] = _P(0.4, 0.2)
    return lm


def _make_open_hand():
    """张开手(无捏合),5 指伸。"""
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.3, 0.7)
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(0.3, 0.5)
    lm[INDEX_PIP] = _P(0.4, 0.22)
    lm[INDEX_TIP] = _P(0.4, 0.2)
    lm[MIDDLE_PIP] = _P(0.5, 0.22)
    lm[MIDDLE_TIP] = _P(0.5, 0.2)
    lm[RING_PIP] = _P(0.6, 0.22)
    lm[RING_TIP] = _P(0.6, 0.2)
    lm[PINKY_PIP] = _P(0.7, 0.22)
    lm[PINKY_TIP] = _P(0.7, 0.2)
    lm[THUMB_TIP] = _P(0.4, 0.55)
    return lm


# ---- Phase 1: events have ts/ts_ms ----

def test_gesture_event_has_timestamp():
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["debug_log"] = False
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_OK
    events = sem.process([_make_ok_hand()], [])
    gesture_events = [e for e in events if e.get("type") == "gesture"]
    assert len(gesture_events) == 1
    e = gesture_events[0]
    assert "ts" in e and "ts_ms" in e
    assert isinstance(e["ts"], float)
    assert isinstance(e["ts_ms"], int)
    assert e["ts_ms"] == int(e["ts"] * 1000)


def test_laser_event_has_timestamp():
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_POINTING_UP
    events = sem.process([_make_open_hand()], [])
    laser_events = [e for e in events if e.get("cmd") == "LASER"]
    assert laser_events
    e = laser_events[0]
    assert "ts" in e and "ts_ms" in e


# ---- Phase 2: GESTURE_END event on release ----

def test_gesture_end_fires_when_going_to_none():
    """OK 持续 → NONE → emit type=gesture_end with previous gesture."""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_OK
    e1 = sem.process([_make_ok_hand()], [])
    assert any(e.get("type") == "gesture" and e["gesture"] == "OK" for e in e1)
    # 放下 → NONE
    sem._classify_static = lambda lm: sem.G_NONE
    e2 = sem.process([_make_ok_hand()], [])
    end_events = [e for e in e2 if e.get("type") == "gesture_end"]
    assert end_events, f"expected gesture_end event, got {e2}"
    assert end_events[0]["gesture"] == "OK"
    assert "ts" in end_events[0]


def test_gesture_end_not_fired_when_continuous_none():
    """持续 NONE 不应发 gesture_end。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_NONE
    sem.process([_make_ok_hand()], [])  # 持续 NONE
    e2 = sem.process([_make_ok_hand()], [])
    end_events = [e for e in e2 if e.get("type") == "gesture_end"]
    assert not end_events


# ---- Phase 5: MOUSE_DOWN/UP for pinch ----

def test_pinch_start_emits_mouse_down_and_click():
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_PALM  # 让 _is_pinching 路径生效
    e1 = sem.process([_make_pinch_hand()], [])
    cmds = [e.get("cmd") for e in e1 if e.get("cmd")]
    assert "MOUSE_CLICK" in cmds, f"missing MOUSE_CLICK in {cmds}"
    assert "MOUSE_DOWN" in cmds, f"missing MOUSE_DOWN in {cmds}"


def test_pinch_release_emits_mouse_up():
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_PALM
    # Round 1:捏合
    sem.process([_make_pinch_hand()], [])
    # Round 2:松开
    sem._classify_static = lambda lm: sem.G_NONE
    e2 = sem.process([_make_open_hand()], [])
    cmds = [e.get("cmd") for e in e2 if e.get("cmd")]
    assert "MOUSE_UP" in cmds, f"missing MOUSE_UP in {cmds}"


# ---- Phase 3: confidence filter ----

class _HandednessItem:
    def __init__(self, score):
        self.score = score


def test_low_confidence_hand_skipped():
    """handedness.score < 阈值的手部应被跳过,不出 gesture 事件。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["low_confidence_threshold"] = 0.7
    sem = GestureSemantics(cfg)
    sem._classify_static = lambda lm: sem.G_OK
    lm = _make_ok_hand()
    # 低置信度
    e1 = sem.process([lm], [[_HandednessItem(0.3)]])
    assert not [e for e in e1 if e.get("type") == "gesture"]
    # 高置信度
    e2 = sem.process([lm], [[_HandednessItem(0.9)]])
    assert [e for e in e2 if e.get("type") == "gesture"]


# ---- Phase 4: relaxed PALM ----

def test_natural_palm_with_slight_finger_bend_now_recognized():
    """自然摊开(手指微弯)现在能识别为 PALM,不再 NONE。

    4 指 tip.y < pip.y - 0.015(relaxed 阈值)即可,
    而旧 strict 阈值 -0.025 偏严。
    """
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # 构造自然摊开手:tip 在 pip 下方 0.020(严守的 strict 阈值是 0.025,卡边)
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(0.3, 0.7)
    for idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[idx] = _P(0.3, 0.5)
    # tip.y = 0.48, pip.y = 0.50,差 0.020 < strict 0.025 但 > relaxed 0.015
    # 用 _extended:tip.y < mcp.y - 0.025 → 0.48 < 0.475? False → not extended
    # 但 relaxed (-0.015): 0.48 < 0.485? True → extended
    for i, (tip_idx, pip_idx) in enumerate([
        (INDEX_TIP, INDEX_PIP), (MIDDLE_TIP, MIDDLE_PIP),
        (RING_TIP, RING_PIP), (PINKY_TIP, PINKY_PIP),
    ]):
        lm[tip_idx] = _P(0.3 + 0.1 * (i+1), 0.48)  # 微弯:tip 比 mcp 高 0.02
        lm[pip_idx] = _P(0.3 + 0.1 * (i+1), 0.50)  # pip = mcp 略上
    # 拇横向
    lm[THUMB_TIP] = _P(0.15, 0.5)  # 远离 index_mcp (0.3, 0.5)
    assert sem._classify_static(lm) == sem.G_PALM, \
        "natural open palm with slight bend should be recognized as PALM"