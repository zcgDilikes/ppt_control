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


def test_toast_positioning(monkeypatch):
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
