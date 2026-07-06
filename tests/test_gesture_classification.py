"""Tests for GestureSemantics._classify_static — 7 unambiguous gestures + mutual exclusion.

Each gesture is tested by:
1. positive case: hand crafted landmarks matching the gesture → assert returned enum
2. negative case: similar-looking pose for the nearest-neighbor gesture → assert NOT that enum

We construct landmarks using a tiny _P dataclass mirroring MediaPipe NormalizedLandmark.
"""

from dataclasses import dataclass

import pytest

from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


@dataclass
class _P:
    x: float
    y: float


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


def _hand(*, thumb_xy, index_tip_xy, middle_tip_xy, ring_tip_xy, pinky_tip_xy,
          wrist_xy=(0.5, 0.7), mcp_xy=(0.5, 0.5)):
    """Build 21-landmark hand with specified tips. Other landmarks default.

    Sets all MCP landmarks to mcp_xy so _hand_size (wrist→middle MCP) gives a
    sensible ~0.20 reference length, not relying on default-zero values.
    For each finger, PIP is set to 0.05 BELOW the TIP when TIP is above MCP
    (extended), or 0.05 ABOVE the TIP when TIP is below MCP (curled).
    This makes:
      extended: tip.y < pip.y - 0.025 (tip clearly above pip)
      curled:   tip.y > pip.y + 0.005 (tip clearly below pip)
    """
    lm = [_P(0.0, 0.0) for _ in range(21)]
    lm[WRIST] = _P(*wrist_xy)
    # Set MCP landmarks (5, 9, 13, 17) to the reference MCP position
    for mcp_idx in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP):
        lm[mcp_idx] = _P(*mcp_xy)
    for tip_xy, tip_idx, pip_idx in (
        (index_tip_xy, INDEX_TIP, INDEX_PIP),
        (middle_tip_xy, MIDDLE_TIP, MIDDLE_PIP),
        (ring_tip_xy, RING_TIP, RING_PIP),
        (pinky_tip_xy, PINKY_TIP, PINKY_PIP),
    ):
        lm[tip_idx] = _P(*tip_xy)
        if tip_xy[1] < mcp_xy[1]:
            # Extended: tip above MCP, so PIP sits below tip.
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1] + 0.05)
        else:
            # Curled: tip below MCP, so PIP sits above tip.
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1] - 0.05)
    lm[THUMB_TIP] = _P(*thumb_xy)
    return lm


def _extended(tip_xy, mcp_xy=(0.5, 0.5)):
    """指伸直:tip 远高于 pip,在 mcp 上方很多。"""
    return (tip_xy[0], mcp_xy[1] - 0.4)


def _curled(tip_xy, mcp_xy=(0.5, 0.5)):
    """指卷曲:tip 在 pip 下方。"""
    return (tip_xy[0], mcp_xy[1] + 0.1)


def _all_extended():
    """4 指都伸直,拇指向侧面。"""
    return _hand(
        thumb_xy=(0.2, 0.5),            # 拇横向(远离 index_mcp)
        index_tip_xy=_extended((0.6, 0.5)),
        middle_tip_xy=_extended((0.7, 0.5)),
        ring_tip_xy=_extended((0.75, 0.5)),
        pinky_tip_xy=_extended((0.78, 0.5)),
    )


def _all_curled_thumb_side():
    """5 指都卷曲,拇贴在掌侧。"""
    return _hand(
        thumb_xy=(0.51, 0.51),           # 拇贴近 index_mcp
        index_tip_xy=_curled((0.55, 0.5)),
        middle_tip_xy=_curled((0.6, 0.5)),
        ring_tip_xy=_curled((0.65, 0.5)),
        pinky_tip_xy=_curled((0.7, 0.5)),
    )


@pytest.fixture
def sem():
    from pc_gesture.config import load_gesture_config
    return GestureSemantics(load_gesture_config())


# ---- positive cases ----

def test_classify_ok(sem):
    """拇指-食指尖接触 + 中/无名/小指都伸。"""
    lm = _hand(
        thumb_xy=(0.55, 0.2),           # 拇指尖贴近 index 尖
        index_tip_xy=(0.55, 0.2),        # 食指尖
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),  # 中指伸
        ring_tip_xy=_extended((0.7, 0.5))[0:1] + (0.2,),
        pinky_tip_xy=_extended((0.75, 0.5))[0:1] + (0.2,),
    )
    assert sem._classify_static(lm) == sem.G_OK


def test_classify_l_sign(sem):
    """拇+食指伸(分开),其它卷曲。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),           # 拇远离(横向)
        index_tip_xy=(0.6, 0.2),        # 食伸
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_L_SIGN


def test_classify_three_fingers(sem):
    """拇+食+中伸,无名+小卷曲。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_THREE_FINGERS


def test_classify_scissors(sem):
    """拇卷 + 食+中伸 + 无名+小卷。"""
    lm = _hand(
        thumb_xy=(0.51, 0.51),          # 拇贴近 mcp
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_SCISSORS


def test_classify_pointing(sem):
    """仅食指伸。"""
    lm = _hand(
        thumb_xy=(0.51, 0.51),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) == sem.G_POINTING_UP


def test_classify_fist(sem):
    """5 指全卷曲。"""
    lm = _all_curled_thumb_side()
    assert sem._classify_static(lm) == sem.G_FIST


def test_classify_palm(sem):
    """5 指全伸。"""
    lm = _all_extended()
    assert sem._classify_static(lm) == sem.G_PALM


# ---- mutual exclusion ----

def test_ok_not_misread_as_three_fingers(sem):
    """OK pose(拇-食接触)不应被判为 THREE_FINGERS。"""
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.55, 0.2),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_extended((0.7, 0.5))[0:1] + (0.2,),
        pinky_tip_xy=_extended((0.75, 0.5))[0:1] + (0.2,),
    )
    assert sem._classify_static(lm) != sem.G_THREE_FINGERS


def test_l_sign_not_misread_as_ok(sem):
    """L pose(拇-食分开)不应被判为 OK。"""
    lm = _hand(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_OK


def test_scissors_not_misread_as_three_fingers(sem):
    """scissors(拇卷)不应被判为 THREE_FINGERS(拇伸)。"""
    lm = _hand(
        thumb_xy=(0.51, 0.51),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_extended((0.65, 0.5))[0:1] + (0.2,),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_THREE_FINGERS


def test_pointing_not_misread_as_scissors(sem):
    """pointing(中指卷)不应被判为 SCISSORS(中指伸)。"""
    lm = _hand(
        thumb_xy=(0.51, 0.51),
        index_tip_xy=_extended((0.6, 0.5))[0:1] + (0.2,),
        middle_tip_xy=_curled((0.65, 0.5)),
        ring_tip_xy=_curled((0.7, 0.5)),
        pinky_tip_xy=_curled((0.75, 0.5)),
    )
    assert sem._classify_static(lm) != sem.G_SCISSORS


def test_partial_curl_still_ok(sem):
    """边界 #1:OK 时三指里只有 2 指完全 EXT,1 指微卷,仍应判 OK。"""
    # middle 真正伸,ring 真正伸,pinky 微卷(只稍低 pip 一点点)
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.55, 0.2),
        middle_tip_xy=(0.65, 0.2),       # 真正伸(pip.y=0.22, tip.y=0.2)
        ring_tip_xy=(0.7, 0.2),         # 真正伸
        pinky_tip_xy=(0.75, 0.51),      # 微卷(pip.y=0.53, tip.y=0.51,差 -0.02 < -0.015 阈值)
    )
    assert sem._classify_static(lm) == sem.G_OK


# ---- dual mode: 所有手势在 A/B 两槽都应触发 ----

def test_dual_mode_a_slot_emits_ok(monkeypatch):
    """Dual 模式下,A 槽的 OK 手势应触发 type=gesture 事件。"""
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    sem = GestureSemantics(cfg)
    lm = _hand(
        thumb_xy=(0.55, 0.2),
        index_tip_xy=(0.58, 0.2),
        middle_tip_xy=(0.65, 0.2),
        ring_tip_xy=(0.7, 0.2),
        pinky_tip_xy=(0.75, 0.2),
    )
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_OK)
    events = sem.process([lm], [], on_send_text=None)
    gesture_events = [e for e in events if e.get("type") == "gesture" and e.get("gesture") == "OK"]
    assert gesture_events, f"dual mode A slot OK did not emit, got {events}"


def test_dual_mode_b_slot_emits_ok(monkeypatch):
    """Dual 模式下,B 槽的 OK 手势也应触发(无 slot 限制)。"""
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "dual"
    cfg.raw["dual_roles_swapped"] = False  # 显式 reset,不依赖磁盘
    sem = GestureSemantics(cfg)
    lm = _hand(
        wrist_xy=(0.7, 0.6),  # wrist x=0.7 → slot B (swapped=False)
        thumb_xy=(0.75, 0.6),
        index_tip_xy=(0.78, 0.2),
        middle_tip_xy=(0.82, 0.2),
        ring_tip_xy=(0.85, 0.2),
        pinky_tip_xy=(0.88, 0.2),
    )
    monkeypatch.setattr(sem, "_classify_static", lambda lm: sem.G_OK)
    events = sem.process([lm], [], on_send_text=None)
    gesture_events = [e for e in events if e.get("type") == "gesture" and e.get("gesture") == "OK"]
    assert gesture_events, f"dual mode B slot OK did not emit, got {events}"


def test_single_mode_b_slot_silently_skipped():
    """Single 模式:只有 A 槽处理。B 槽(hand 出现在画面右半边)的事件应被 engine 的 _assign_slot 跳过。

    Note: process() 内部 _assign_slot 把 wrist.x >= 0.5 的手分配到 B 槽,
    而 single mode 下 _semantics.process() 不会处理 B 槽的手(只处理 A 槽)。
    """
    cfg = load_gesture_config()
    cfg.raw["operator_mode"] = "single"
    cfg.raw["dual_roles_swapped"] = False  # 显式 reset,不依赖磁盘
    sem = GestureSemantics(cfg)
    lm = _hand(
        wrist_xy=(0.7, 0.6),  # wrist x=0.7 → slot B
        thumb_xy=(0.75, 0.6),
        index_tip_xy=(0.78, 0.2),
        middle_tip_xy=(0.82, 0.2),
        ring_tip_xy=(0.85, 0.2),
        pinky_tip_xy=(0.88, 0.2),
    )
    sem._classify_static = lambda lm: sem.G_OK  # would emit if processed
    events = sem.process([lm], [], on_send_text=None)
    # 单人模式 + B 槽 → 不应该有 type=gesture OK 事件
    gesture_events = [e for e in events if e.get("type") == "gesture" and e.get("gesture") == "OK"]
    assert gesture_events == [], f"single mode B slot should be skipped, got {gesture_events}"