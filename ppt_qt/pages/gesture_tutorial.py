"""P2.1:交互式教程对话框 — 9-event 自检清单。

用户启动后看到 9 个手势-动作对,自己做一遍后手动勾选。
全部勾选完会有祝贺信息。

不做强制逐个 demo(MVP 价值低,实施复杂)。
让用户按自己的节奏学。
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from pc_gesture.config import GESTURES, ACTIONS


# 9 个 tip-touch 事件中文描述 + emoji
TUTORIAL_STEPS: List[Dict] = [
    {"id": "L_HAND_INDEX",     "emoji": "👆", "name": "左手拇指触食指"},
    {"id": "L_HAND_MIDDLE",    "emoji": "☝",  "name": "左手拇指触中指"},
    {"id": "L_HAND_RING",      "emoji": "💍", "name": "左手拇指触无名指"},
    {"id": "L_HAND_PINKY",     "emoji": "🤙", "name": "左手拇指触小拇指"},
    {"id": "R_HAND_INDEX",     "emoji": "👆", "name": "右手拇指触食指"},
    {"id": "R_HAND_MIDDLE",    "emoji": "🖕", "name": "右手拇指触中指"},
    {"id": "R_HAND_RING",      "emoji": "💍", "name": "右手拇指触无名指"},
    {"id": "R_HAND_PINKY",     "emoji": "🤙", "name": "右手拇指触小拇指"},
    {"id": "HANDS_INTERLOCK",  "emoji": "🤝", "name": "双手十指相扣(2s dwell)"},
]


class GestureTutorialDialog(QDialog):
    """P2.1:9-event 自检教程对话框。"""

    def __init__(self, *, cfg, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self.setWindowTitle("9-event 交互教程")
        self.setModal(True)
        self.resize(640, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # 顶部说明
        title = QLabel("📚 9 个手势速学(做一遍后勾选)")
        title.setStyleSheet("color:#ffffff;font-size:16px;font-weight:600;")
        layout.addWidget(title)

        instruction = QLabel(
            "新用户建议顺序:先学一只手(例:左手食指),熟悉 5 秒内能稳定触发,\n"
            "再加新手势。所有 8 个单手 tip-touch 试过后再试 HANDS_INTERLOCK(双手 2 秒持续)。"
        )
        instruction.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        # 滚动区 + 列表
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(6)
        self._checkboxes: Dict[str, QCheckBox] = {}
        for step in TUTORIAL_STEPS:
            row = self._build_step_row(step)
            scroll_layout.addWidget(row)
        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # 底部按钮
        btn_box = QDialogButtonBox(self)
        self._finish_btn = QPushButton("完成")
        self._finish_btn.setDefault(True)
        self._finish_btn.clicked.connect(self.accept)
        btn_box.addButton(self._finish_btn, QDialogButtonBox.AcceptRole)
        layout.addWidget(btn_box)

    def _build_step_row(self, step: dict) -> QFrame:
        """单行:checkbox + emoji + 名字 + 关联动作。"""
        row = QFrame()
        row.setStyleSheet(
            "background:rgba(255,255,255,0.05);border-radius:6px;padding:6px;"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(10)

        cb = QCheckBox()
        self._checkboxes[step["id"]] = cb
        cb.toggled.connect(lambda checked, s=step: self._on_toggle(s, checked))
        h.addWidget(cb)

        emoji_lbl = QLabel(step["emoji"])
        emoji_lbl.setStyleSheet("font-size:18px;")
        emoji_lbl.setFixedWidth(28)
        h.addWidget(emoji_lbl)

        name_lbl = QLabel(step["name"])
        name_lbl.setStyleSheet("color:#ffffff;font-size:13px;")
        h.addWidget(name_lbl, 1)

        # 关联动作 — 读 cfg.tip_bindings
        action = None
        if hasattr(self._cfg, "tip_bindings"):
            action = self._cfg.tip_bindings.get(step["id"])
        action_text = f"→ {action}" if action else "→ (未绑定)"
        action_lbl = QLabel(action_text)
        action_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        h.addWidget(action_lbl)

        return row

    def _on_toggle(self, step: dict, checked: bool) -> None:
        """勾选时把整行加个绿色高亮;取消时复原。"""
        # 找父 widget 改 styleSheet。Qt 没有 parent 引用但我们可以从 sender
        sender = self.sender()
        if sender and checked:
            sender.setStyleSheet("color:#86efac;font-size:11px;font-weight:600;")
        elif sender:
            sender.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")

    def completed_count(self) -> int:
        return sum(1 for cb in self._checkboxes.values() if cb.isChecked())

    def is_all_completed(self) -> bool:
        return self.completed_count() == len(self._checkboxes)
