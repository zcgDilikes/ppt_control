"""Tests for info.txt 六.1 role mapping centralization.

验证 _resolve_role_flags 集中返回 produce_laser/produce_static/produce_pinch
3 个布尔。之前 3 个 if 分支散落在 _process_one_hand,refactor 后抽出来单测可验证。
"""

import pytest

from pc_gesture.config import load_gesture_config
from pc_gesture.semantics import GestureSemantics


def test_resolve_role_flags_single_mode():
    """single mode:
      - A 槽:laser=static=pinch=True(主手)
      - B 槽:全部 False(忽略)
    """
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem.cfg.raw["operator_mode"] = "single"
    laser, static, pinch = sem._resolve_role_flags(is_single=True, slot="A")
    assert laser is True
    assert static is True
    assert pinch is True
    laser, static, pinch = sem._resolve_role_flags(is_single=True, slot="B")
    assert laser is False
    assert static is False
    assert pinch is False


def test_resolve_role_flags_dual_mode():
    """dual mode:
      - A 槽:static=True(导航手势都触发),laser=pinch=False
      - B 槽:全部 True(指控手)
    """
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    sem.cfg.raw["operator_mode"] = "dual"
    laser, static, pinch = sem._resolve_role_flags(is_single=False, slot="A")
    assert laser is False
    assert static is True
    assert pinch is False
    laser, static, pinch = sem._resolve_role_flags(is_single=False, slot="B")
    assert laser is True
    assert static is True
    assert pinch is True


def test_resolve_role_flags_ignores_other_slots():
    """未知 slot 字符串返回全 False(防御性)。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    laser, static, pinch = sem._resolve_role_flags(is_single=True, slot="Z")
    assert (laser, static, pinch) == (False, False, False)


def test_resolve_role_flags_returns_tuple():
    """返回 tuple 不是 list,便于解构。"""
    cfg = load_gesture_config()
    sem = GestureSemantics(cfg)
    result = sem._resolve_role_flags(is_single=True, slot="A")
    assert isinstance(result, tuple)
    assert len(result) == 3