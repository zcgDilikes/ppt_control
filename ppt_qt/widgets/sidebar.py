from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Signal, Qt


class Sidebar(QWidget):
    currentChanged = Signal(int)

    def __init__(self, *, items, current=0, on_change=None, on_exit=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(72)
        self._items = items
        self._buttons = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 16, 0, 16)
        v.setSpacing(8)
        logo = QLabel("P")
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "background:#ff6e7f;color:#fff;border-radius:10px;font-size:18px;font-weight:700;"
        )
        logo.setFixedSize(36, 36)
        v.addWidget(logo, 0, Qt.AlignHCenter)
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(255,255,255,30);")
        v.addWidget(sep)
        for i, (label, icon) in enumerate(items):
            btn = QPushButton(icon)
            btn.setFixedSize(40, 40)
            btn.setCheckable(True)
            btn.setStyleSheet(
                """
                QPushButton { background: transparent; color: rgba(255,255,255,180);
                              border: none; border-radius: 10px; font-size: 18px; }
                QPushButton:checked { background: rgba(255,255,255,40); color: #fff; }
                QPushButton:hover { background: rgba(255,255,255,20); }
            """
            )
            btn.setToolTip(label)
            btn.clicked.connect(lambda _checked=False, idx=i: self._select(idx))
            self._buttons.append(btn)
            v.addWidget(btn, 0, Qt.AlignHCenter)
        v.addStretch(1)
        if on_exit is not None:
            exit_btn = QPushButton("⌬")
            exit_btn.setFixedSize(40, 40)
            exit_btn.setStyleSheet(
                "background:rgba(255,255,255,30);color:rgba(255,255,255,200);border:none;border-radius:10px;"
            )
            exit_btn.setToolTip("退出")
            exit_btn.clicked.connect(on_exit)
            v.addWidget(exit_btn, 0, Qt.AlignHCenter)
        self._select(current)
        if on_change is not None:
            self.currentChanged.connect(on_change)

    def _select(self, idx):
        for i, b in enumerate(self._buttons):
            b.setChecked(i == idx)
        self.currentChanged.emit(idx)