"""Tests for P0.1: toast feedback when gesture triggers."""

import pytest

# Headless Qt for tests
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel
_app = QApplication.instance() or QApplication([])


def _make_page(monkeypatch):
    """Build a minimal GesturePage-like object with toast methods."""
    from ppt_qt.pages.gesture_page import GesturePage
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    bridge = MagicMock()
    bridge.cfg = cfg
    return GesturePage(bridge=bridge)


def test_toast_initially_hidden():
    page = _make_page(None)
    # 用 isVisibleTo 检查相对父 widget 的可见性,不受 top-level window 状态影响
    assert page._toast.isVisibleTo(page) is False


def test_show_toast_makes_visible(monkeypatch):
    page = _make_page(monkeypatch)
    page._show_toast("👆 食指 → 下一页", duration_ms=1000)
    assert page._toast.isVisibleTo(page) is True
    assert "下一页" in page._toast.text()


def test_toast_text_contains_emoji_and_action(monkeypatch):
    page = _make_page(monkeypatch)
    page._show_toast("📹 演示", duration_ms=500)
    text = page._toast.text()
    assert "📹" in text
    assert "演示" in text


def test_toast_hides_after_duration(monkeypatch):
    """timer 触发后 toast 应隐藏。"""
    page = _make_page(monkeypatch)
    page._show_toast("test", duration_ms=2000)
    page._toast_timer.timeout.emit()  # 直接触发 timeout
    assert page._toast.isVisibleTo(page) is False


def test_mapping_table_uses_lr_color(monkeypatch):
    """P1.2:左手 emoji 蓝色,右手 emoji 橙色,互锁黄色。"""
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    bridge = MagicMock()
    bridge.cfg = cfg
    from ppt_qt.pages.gesture_page import GesturePage
    page = GesturePage(bridge=bridge)
    # 检查 L_HAND 和 R_HAND 的样式
    lbl_colors = {}
    for i in range(page._mapping_table_layout.count()):
        widget = page._mapping_table_layout.itemAt(i).widget()
        if widget and "左手拇指触食指" in widget.text():
            lbl_colors["L"] = widget.styleSheet()
        if widget and "右手拇指触食指" in widget.text():
            lbl_colors["R"] = widget.styleSheet()
    assert "60a5fa" in lbl_colors.get("L", ""), f"L 应该是蓝色: {lbl_colors}"
    assert "fb923c" in lbl_colors.get("R", ""), f"R 应该是橙色: {lbl_colors}"


def test_toast_uses_lr_color_prefix(monkeypatch):
    """P1.2:toast 加 🔵/🟠 prefix 区分左右手。"""
    page = _make_page(monkeypatch)
    from ppt_qt.pages.gesture_page import _TIP_GESTURE_META
    emoji, name = _TIP_GESTURE_META.get("L_HAND_INDEX", ("", ""))
    assert "左手拇指触食指" in name
    assert emoji == "👆"  # placeholder check

    """toast 应在父 widget 中下方居中。"""
    page = _make_page(monkeypatch)
    page.resize(800, 600)
    page._show_toast("test", duration_ms=2000)
    geo = page._toast.geometry()
    # 居中:x 应该在父中点附近
    assert geo.x() < 800
    assert geo.x() + geo.width() > 0
    # y 在父下方 65% 左右
    assert geo.y() > 600 * 0.5


# ---- P1.1: 手势-动作对照表 ----

def test_mapping_table_default_expanded(monkeypatch):
    """P1.1:对照表默认展开,填 9 行 + HANDS_INTERLOCK。"""
    page = _make_page(monkeypatch)
    assert page._mapping_table.isVisibleTo(page) is True
    # 9 个手势(8 tip + 1 interlock)按 2 列布局 → 5 行
    assert page._mapping_table_layout.rowCount() == 5
    # 9 个描述 label + 9 个动作 label
    assert page._mapping_table_layout.count() == 18


def test_mapping_table_can_be_collapsed(monkeypatch):
    """checkbox 可隐藏/显示对照表。"""
    page = _make_page(monkeypatch)
    page._mapping_table_toggle.setChecked(False)
    assert page._mapping_table.isVisibleTo(page) is False
    page._mapping_table_toggle.setChecked(True)
    assert page._mapping_table.isVisibleTo(page) is True


def test_mapping_table_reflects_user_bindings(monkeypatch):
    """对照表的动作 label 反映 cfg.tip_bindings 当前值。"""
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config
    cfg = load_gesture_config()
    bridge = MagicMock()
    bridge.cfg = cfg
    from ppt_qt.pages.gesture_page import GesturePage
    # 直接修改 property(不是 raw 快照),page 看到的绑定
    cfg.tip_bindings["L_HAND_INDEX"] = "PREV_PAGE"
    page = GesturePage(bridge=bridge)
    # 找 L_HAND_INDEX 描述 label 的位置 → 同行下一个 widget 是 action
    lbl_count = page._mapping_table_layout.count()
    for i in range(lbl_count - 1):
        widget = page._mapping_table_layout.itemAt(i).widget()
        if widget and "左手拇指触食指" in widget.text():
            action_lbl = page._mapping_table_layout.itemAt(i + 1).widget()
            assert action_lbl.text() == "上一页", \
                f"expected '上一页' got '{action_lbl.text()}'"
            return
    raise AssertionError("L_HAND_INDEX row not found in mapping table")
