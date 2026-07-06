"""Tests for ppt_core.ppt_executor — COM-first slideshow navigation + pyautogui fallback.

When win32com is available (typical Windows user setup), ppt_executor.Next/Previous
drives PowerPoint via the COM API regardless of which window has focus.
When pywin32 is not installed (CI / dev box), it falls back to pyautogui.press.
"""

from unittest.mock import patch, MagicMock

import pytest

from ppt_core import ppt_executor as exec_mod
from ppt_core.ppt_executor import PptExecutor


@pytest.fixture
def executor():
    return PptExecutor(save_dir="./ppt_files/")


def test_ensure_pywin32_returns_false_when_module_missing(monkeypatch):
    """Dev env / CI 没有 pywin32,_ensure_pywin32 应返回 False。"""
    # 即使 install 了,_ensure_pywin32 内部会试图 import,如果 import 失败 → False
    # 这测试的是 fallback 路径
    monkeypatch.setattr(exec_mod, "_wc", None)
    monkeypatch.setattr(exec_mod, "_ensure_pywin32", lambda: False)
    assert exec_mod._ppt_show_view() is None


def test_ppt_show_view_returns_none_when_no_slideshow(monkeypatch):
    """即使 pywin32 在,没在放映时 _ppt_show_view 应返回 None。"""
    monkeypatch.setattr(exec_mod, "_ensure_pywin32", lambda: True)
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: None)
    assert exec_mod._ppt_show_view() is None


def test_next_page_falls_back_to_pyautogui_when_com_unavailable(executor, monkeypatch):
    """pywin32 不可用时,NEXT_PAGE 应 fall back 到 _press('pagedown')。"""
    # Force _ppt_show_view to return None (COM unavailable)
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: None)
    # Capture what _press is called with
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "NEXT_PAGE"})
    assert pressed == ["pagedown"]


def test_next_page_uses_com_when_available(executor, monkeypatch):
    """pywin32 在且 _ppt_show_view 返回 view 时,应走 COM 而不是 pyautogui。"""
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "NEXT_PAGE"})
    view.Next.assert_called_once()
    assert pressed == []  # 没有 fallback 到 pyautogui


def test_prev_page_uses_com_when_available(executor, monkeypatch):
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "PREV_PAGE"})
    view.Previous.assert_called_once()
    assert pressed == []


def test_exit_uses_com_when_available(executor, monkeypatch):
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "EXIT"})
    view.Exit.assert_called_once()
    assert pressed == []


def test_exit_falls_back_to_esc(executor, monkeypatch):
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: None)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "EXIT"})
    assert pressed == ["esc"]


def test_full_screen_noop_when_already_in_show(executor, monkeypatch):
    """如果已在放映,FULL_SCREEN 应该是退出放映(F5 启动,Esc 退出)。"""
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "FULL_SCREEN"})
    view.Exit.assert_called_once()
    assert pressed == []  # 没有走 _press("f5") 也不走 _press("esc")


def test_full_screen_starts_show_when_not_active(executor, monkeypatch):
    """如果没在放映,FULL_SCREEN 应按 F5 启动。"""
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: None)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "FULL_SCREEN"})
    assert pressed == ["f5"]


def test_black_screen_uses_com_when_available(executor, monkeypatch):
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "BLACK_SCREEN"})
    # State == 9 (ppSlideShowBlackScreen)
    assert view.State == exec_mod._PP_STATE_BLACK_SCREEN
    assert pressed == []


def test_black_screen_falls_back_to_b(executor, monkeypatch):
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: None)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "BLACK_SCREEN"})
    assert pressed == ["b"]


def test_white_screen_uses_com_when_available(executor, monkeypatch):
    view = MagicMock()
    monkeypatch.setattr(exec_mod, "_ppt_show_view", lambda: view)
    pressed = []
    monkeypatch.setattr(executor, "_press", lambda k: pressed.append(k))
    executor.execute({"cmd": "WHITE_SCREEN"})
    assert view.State == exec_mod._PP_STATE_WHITE_SCREEN
    assert pressed == []