"""Tests for P2.1: GestureTutorialDialog 9-event 自检教程。"""

import pytest

# Headless Qt
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])


def test_tutorial_dialog_loads():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    bridge = MagicMock()
    bridge.cfg = cfg
    dlg = GestureTutorialDialog(cfg=cfg, parent=None)
    assert dlg.windowTitle() == "9-event 交互教程"


def test_tutorial_has_9_steps():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog, TUTORIAL_STEPS
    assert len(TUTORIAL_STEPS) == 9
    # 8 个 tip-touch + 1 个 interlock
    tip_steps = [s for s in TUTORIAL_STEPS if s["id"].startswith("L_HAND_") or s["id"].startswith("R_HAND_")]
    interlock_steps = [s for s in TUTORIAL_STEPS if s["id"] == "HANDS_INTERLOCK"]
    assert len(tip_steps) == 8
    assert len(interlock_steps) == 1


def test_tutorial_checkboxes_exist():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    dlg = GestureTutorialDialog(cfg=cfg, parent=None)
    assert len(dlg._checkboxes) == 9
    # 每个 checkbox 初始未勾选
    assert dlg.completed_count() == 0


def test_tutorial_completed_count_increments():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    dlg = GestureTutorialDialog(cfg=cfg, parent=None)
    dlg._checkboxes["L_HAND_INDEX"].setChecked(True)
    dlg._checkboxes["L_HAND_MIDDLE"].setChecked(True)
    assert dlg.completed_count() == 2
    assert dlg.is_all_completed() is False


def test_tutorial_all_completed():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    dlg = GestureTutorialDialog(cfg=cfg, parent=None)
    for cb in dlg._checkboxes.values():
        cb.setChecked(True)
    assert dlg.completed_count() == 9
    assert dlg.is_all_completed() is True


def test_tutorial_step_row_shows_action_from_config():
    from ppt_qt.pages.gesture_tutorial import GestureTutorialDialog
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    cfg.tip_bindings["L_HAND_INDEX"] = "FULL_SCREEN"
    dlg = GestureTutorialDialog(cfg=cfg, parent=None)
    cb = dlg._checkboxes["L_HAND_INDEX"]
    # 验证 row 显示了 "→ FULL_SCREEN"
    row = cb.parent()
    action_label = None
    for child in row.children():
        if isinstance(child, type(dlg._checkboxes["L_HAND_INDEX"].parent())):
            continue
    # 简化:从 row 的 layout 找 QLabel 含 → 字符
    layout = row.layout()
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w and "FULL_SCREEN" in w.text():
            action_label = w.text()
            break
    assert action_label is not None
    assert "FULL_SCREEN" in action_label
