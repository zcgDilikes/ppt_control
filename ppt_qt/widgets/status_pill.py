from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt


class StatusPill(QWidget):
    def __init__(self, *, status_text="", button_text="", on_button=None, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 8, 8, 8)
        h.setSpacing(10)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet("background:#94a3b8;border-radius:4px;")
        h.addWidget(self._dot, 0, Qt.AlignVCenter)
        self._text = QLabel(status_text)
        self._text.setStyleSheet("color:#fff;font-size:12px;")
        h.addWidget(self._text, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self._btn = QPushButton(button_text)
        self._btn.setObjectName("PrimaryButton")
        self._btn.setVisible(bool(button_text))
        if on_button is not None:
            self._btn.clicked.connect(on_button)
        h.addWidget(self._btn, 0, Qt.AlignVCenter)

    def set_status(self, text):
        self._text.setText(text)

    def set_ok(self, ok):
        color = "#94a3b8" if ok is None else ("#34d399" if ok else "#f87171")
        glow = f"box-shadow:0 0 6px {color};" if ok else ""
        self._dot.setStyleSheet(f"background:{color};border-radius:4px;{glow}")

    def set_button_text(self, text):
        self._btn.setText(text)
        self._btn.setVisible(bool(text))
