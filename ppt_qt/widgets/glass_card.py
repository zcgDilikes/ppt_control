from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class GlassCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassCard")
        self.setAttribute(Qt.WA_StyledBackground, True)