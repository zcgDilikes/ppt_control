# tests/test_smart_tray.py
import time
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from ppt_qt.widgets.smart_tray import SmartTray


def test_smart_tray_populates_top_n():
    dispatcher = MagicMock()
    # 用相对 now 的时间戳(避免 30 天窗口过滤掉)
    now = time.time()
    history = [
        ("NEXT_PAGE", now - 300),
        ("NEXT_PAGE", now - 200),
        ("NEXT_PAGE", now - 100),
        ("BLACK_SCREEN", now - 50),
        ("PREV_PAGE", now - 25),
    ]
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    # 1 (占位) + 3 (top-3 unique) = 4
    assert tray.count() == 4
    # 按频次降序,NEXT_PAGE 出现 3 次排第一
    # itemText(0) 是占位"⭐ 常用",itemText(1) 是第一候选
    assert tray.itemText(1) == "下一页"  # 或 "NEXT_PAGE" 看实现


def test_smart_tray_dispatches_on_click():
    dispatcher = MagicMock()
    now = time.time()
    history = [("NEXT_PAGE", now - i) for i in range(5)]
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    # 模拟点击第一项(跳过占位,index 0 是占位)
    first_idx = 1
    action_data = tray.itemData(first_idx)
    assert action_data == "NEXT_PAGE"
    # 直接调用 activated signal
    tray.activated.emit(1)
    # 验证 dispatcher 被调
    dispatcher.dispatch.assert_called_once()
    call_args = dispatcher.dispatch.call_args[0][0]
    assert call_args.get("cmd") == "NEXT_PAGE"


def test_smart_tray_handles_empty_history():
    dispatcher = MagicMock()
    tray = SmartTray(history=[], dispatcher=dispatcher, top_n=3)
    # 占位项 1 个,无候选
    assert tray.count() == 1  # 占位符 still there


def test_smart_tray_excludes_system_commands():
    """OPEN_PPT/SCREENSHOT 不进 SmartTray 候选(防止被点)。"""
    dispatcher = MagicMock()
    now = time.time()
    history = [
        ("OPEN_PPT", now - 300),
        ("OPEN_PPT", now - 200),
        ("OPEN_PPT", now - 100),
        ("NEXT_PAGE", now - 50),
    ]
    tray = SmartTray(history=history, dispatcher=dispatcher, top_n=3)
    # OPEN_PPT 不应出现
    items_text = [tray.itemText(i) for i in range(tray.count())]
    assert "OPEN_PPT" not in items_text
    assert "下一页" in items_text or "NEXT_PAGE" in items_text
