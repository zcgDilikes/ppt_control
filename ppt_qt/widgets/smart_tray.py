# ppt_qt/widgets/smart_tray.py
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox
from ppt_core.hand_habits import HabitAnalyzer
from ppt_core.hand_habits_storage import load_habits
import os

# 动作到中文的映射(复用 gesture_page 的 _ACTION_LABEL 思路)
_ACTION_LABEL = {
    "NEXT_PAGE": "下一页",
    "PREV_PAGE": "上一页",
    "BLACK_SCREEN": "黑屏",
    "WHITE_SCREEN": "白屏",
    "FULL_SCREEN": "从头放映",
    "FROM_CURRENT": "从当前放映",
    "EXIT": "退出放映",
    "SCREENSHOT": "截屏",
    "OPEN_PPT": "打开PPT",
}


class SmartTray(QComboBox):
    """顶栏"⭐ 常用"快捷动作下拉。"""

    activated_action = Signal(str)

    def __init__(self, *, history=None, dispatcher=None, top_n=3, parent=None):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._top_n = top_n
        # 默认占位符
        self.addItem("⭐ 常用")
        self.setEnabled(False)
        if history is not None:
            self.refresh(history)
        self.activated.connect(self._on_activated)

    def refresh(self, history):
        """根据历史动作刷新 top-N 候选。"""
        # 保留占位项
        self.clear()
        self.addItem("⭐ 常用")
        analyzer = HabitAnalyzer(history)
        top_actions = analyzer.top_n_actions(self._top_n)
        if not top_actions:
            self.setEnabled(False)
            return
        for action in top_actions:
            label = _ACTION_LABEL.get(action, action)
            self.addItem(label, userData=action)
        self.setEnabled(True)

    def _on_activated(self, index):
        if index == 0:
            return  # 跳过占位项
        action = self.itemData(index)
        if not action:
            return
        self.activated_action.emit(action)
        if self._dispatcher:
            self._dispatcher.dispatch({"cmd": action})


def make_smart_tray_from_user_data(user_data_dir, dispatcher=None, top_n=3):
    """工厂函数:从 user_data/habits.json 读历史,创建 SmartTray。"""
    history = load_habits(user_data_dir)
    return SmartTray(history=history, dispatcher=dispatcher, top_n=top_n)
