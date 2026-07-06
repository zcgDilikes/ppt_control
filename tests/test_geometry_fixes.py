"""Tests for info.txt 二.1 + 二.3 geometry improvements.

二.1: Y 模糊(hand sideways)时,启用 2D 距离兜底判定伸直
二.3: L_SIGN 需要 thumb 明显伸出(l_sign_thumb_extend_ratio,默认 0.30),
     防止「微伸」误判 L_SIGN

正常 Y 方向的手不进入 2D 路径,保持原有行为不变。
"""

import pytest

from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


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


def _hand_sideways(thumb_xy, index_tip_xy, middle_tip_xy, ring_tip_xy, pinky_tip_xy,
                    wrist_xy=(0.5, 0.5), mcp_xy=(0.5, 0.5), ambiguous=True):
    """构造「手侧放」landmark:tip 与 pip 在同一 Y 水平(手指横向)。

    ambiguous=True (默认): tip.y == pip.y → 触发 Y 模糊 → 2D 距离兜底
    ambiguous=False: tip.y 明显 < pip.y → Y 直接判 strict extended
    """
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
        if ambiguous:
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1])  # tip.y == pip.y (侧放)
        else:
            lm[pip_idx] = _P(tip_xy[0], tip_xy[1] + 0.05)  # pip below tip (正常)
    lm[THUMB_TIP] = _P(*thumb_xy)
    return lm


def _hand_vertical(thumb_xy, index_tip_xy, middle_tip_xy, ring_tip_xy, pinky_tip_xy,
                   wrist_xy=(0.5, 0.7), mcp_xy=(0.5, 0.5)):
    """构造「正常 Y 方向」手:tip.y 跟 pip.y 不同,直接走 Y 路径。

    tip.y < mcp.y: 伸直 → pip 在 tip 下方 0.05
    tip.y > mcp.y: 卷曲 → pip 在 tip 上方 0.05
    """
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

def test_new_geometry_defaults_present():
    cfg = load_gesture_config()
    s = cfg.sensitivity
    assert s["ambiguous_y_tolerance"] == 0.005
    assert s["ext_2d_ratio"] == 0.85
    assert s["l_sign_thumb_extend_ratio"] == 0.30


# ---- 二.1: Y 模糊时 2D 兜底 ----

def test_sideways_open_hand_recognized_as_palm():
    """手侧放,4 指水平伸直。Y 模糊,2D 距离判伸直 → PALM。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # 拇横向 + 4 指水平伸出。tip 离 MCP 远 → 2D 距离 > 0.85*size
    # wrist=(0.5, 0.7), mcp=(0.5, 0.5) → hand_size = 0.2
    lm = _hand_sideways(
        thumb_xy=(0.2, 0.5),
        index_tip_xy=(0.9, 0.5),  # 离 MCP 0.4 → 2.0*size
        middle_tip_xy=(0.95, 0.5),
        ring_tip_xy=(1.0, 0.5),
        pinky_tip_xy=(1.05, 0.5),
        wrist_xy=(0.5, 0.7),  # 真实手部几何
    )
    assert sem._classify_static(lm) == sem.G_PALM


def test_sideways_curled_fingers_not_misread_as_extended():
    """手侧放,4 指卷曲(弯回掌心)。2D 距离小,不该判伸直。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # 4 指 tip 靠近 MCP(卷曲)→ 2D 距离小
    lm = _hand_sideways(
        thumb_xy=(0.4, 0.5),
        index_tip_xy=(0.55, 0.5),  # 离 MCP (0.5, 0.5) 0.05 = 0.25*size
        middle_tip_xy=(0.55, 0.5),
        ring_tip_xy=(0.55, 0.5),
        pinky_tip_xy=(0.55, 0.5),
        wrist_xy=(0.5, 0.7),  # 真实手部几何,size=0.2
    )
    # 4 指 2D 卷 → 不该判 PALM
    assert sem._classify_static(lm) != sem.G_PALM


def test_normal_vertical_hand_unaffected():
    """正常垂直手(非侧放)走 Y 路径,行为不变。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # 同 test_classify_palm 的姿势:4 指上伸,tip.y 明显 < pip.y
    lm = _hand_vertical(
        thumb_xy=(0.2, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=(0.7, 0.2),
        ring_tip_xy=(0.75, 0.2),
        pinky_tip_xy=(0.78, 0.2),
    )
    assert sem._classify_static(lm) == sem.G_PALM


# ---- 二.3: L_SIGN 需要 thumb 明显伸出 ----

def test_slight_thumb_extension_not_misread_as_l_sign():
    """拇指「微伸」(ratio 0.20)不应触发 L_SIGN。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # thumb (0.48, 0.48), mcp (0.5, 0.5), dist ≈ 0.028*sqrt(2) ≈ 0.04
    # size = 0.2, ratio = 0.20
    # 0.20 > 0.18(原 extended 阈值)但 < 0.30(新 l_sign 阈值)→ 不判 L
    lm = _hand_vertical(
        thumb_xy=(0.48, 0.48),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=(0.65, 0.5),  # 卷
        ring_tip_xy=(0.7, 0.5),
        pinky_tip_xy=(0.75, 0.5),
    )
    result = sem._classify_static(lm)
    assert result != sem.G_L_SIGN, f"slight thumb ext should not be L, got {result}"


def test_strong_thumb_extension_still_l_sign():
    """拇指明显伸出(L 形)仍是 L_SIGN。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    # thumb (0.15, 0.5), mcp (0.5, 0.5), dist = 0.35
    # ratio = 0.35/0.2 = 1.75 >> 0.30 → L_SIGN
    lm = _hand_vertical(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=(0.65, 0.5),
        ring_tip_xy=(0.7, 0.5),
        pinky_tip_xy=(0.75, 0.5),
    )
    assert sem._classify_static(lm) == sem.G_L_SIGN


def test_user_can_lower_l_sign_threshold():
    """调小 l_sign_thumb_extend_ratio,降低 L_SIGN 难度。

    拇指 ratio 0.22(在旧阈值 0.18 之上、新阈值 0.30 之下):
    - 默认 0.30 阈值下:不判 L_SIGN
    - 调到 0.15 阈值下:判 L_SIGN
    """
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["l_sign_thumb_extend_ratio"] = 0.15
    sem = GestureSemantics(cfg)
    # thumb (0.46, 0.48) → dist ≈ 0.0447, ratio ≈ 0.224(在 0.18-0.30 之间)
    lm = _hand_vertical(
        thumb_xy=(0.46, 0.48),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=(0.65, 0.5),
        ring_tip_xy=(0.7, 0.5),
        pinky_tip_xy=(0.75, 0.5),
    )
    assert sem._classify_static(lm) == sem.G_L_SIGN


# ---- 二.1 + 二.3 异常配置 fallback ----

def test_invalid_geometry_threshold_falls_back():
    """Y 模糊阈值给字符串/None 时,fallback 到默认值。"""
    cfg = load_gesture_config()
    cfg.raw["sensitivity"]["ambiguous_y_tolerance"] = "bad"
    cfg.raw["sensitivity"]["l_sign_thumb_extend_ratio"] = None
    sem = GestureSemantics(cfg)
    # 标准 L 手应该正常识别
    lm = _hand_vertical(
        thumb_xy=(0.15, 0.5),
        index_tip_xy=(0.6, 0.2),
        middle_tip_xy=(0.65, 0.5),
        ring_tip_xy=(0.7, 0.5),
        pinky_tip_xy=(0.75, 0.5),
    )
    assert sem._classify_static(lm) == sem.G_L_SIGN