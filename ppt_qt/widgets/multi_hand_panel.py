# ppt_qt/widgets/multi_hand_panel.py
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel


_SLOT_COLORS = {
    "A": "#60a5fa",  # 蓝
    "B": "#fb923c",  # 橙
    "C": "#a855f7",  # 紫(第三手)
}


class MultiHandPanel(QFrame):
    """3-hand 状态可视化面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MultiHandPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        title = QLabel("🖐  多手状态")
        title.setStyleSheet("color:#ffffff;font-size:12px;font-weight:600;")
        layout.addWidget(title)
        # 3 个 slot block
        self._blocks = {}
        for slot in ["A", "B", "C"]:
            block = QFrame()
            color = _SLOT_COLORS[slot]
            block.setStyleSheet(
                f"background:rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.2);"
                f"border-left:3px solid {color};border-radius:4px;padding:6px;"
            )
            block_l = QVBoxLayout(block)
            block_l.setContentsMargins(6, 4, 6, 4)
            block_l.setSpacing(2)
            slot_lbl = QLabel(f"Slot {slot}")
            slot_lbl.setStyleSheet(f"color:{color};font-size:11px;font-weight:600;")
            block_l.addWidget(slot_lbl)
            status_lbl = QLabel("—")
            status_lbl.setStyleSheet("color:rgba(255,255,255,200);font-size:10px;")
            block_l.addWidget(status_lbl)
            setattr(self, f"_slot_{slot.lower()}", block)
            setattr(self, f"_slot_{slot.lower()}_status", status_lbl)
            self._blocks[slot] = status_lbl
            layout.addWidget(block)

    def update_from_snapshot(self, snapshot):
        """更新 3 个 slot 状态(从 FrameSnapshot 读 hands)。"""
        for slot in ["A", "B", "C"]:
            self._blocks[slot].setText("—")
        for hand in snapshot.hands:
            slot = hand.slot
            if slot in self._blocks:
                self._blocks[slot].setText(
                    f"person {hand.person_id} | {hand.static_gesture or 'NONE'}"
                )