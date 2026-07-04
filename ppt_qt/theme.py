from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtCore import QRect

SUNSET_TOP = "#ff6e7f"
SUNSET_MID = "#ffd3d3"
SUNSET_BOT = "#bfe9ff"
GLASS_BG = "rgba(20, 20, 30, 200)"
GLASS_BORDER = "rgba(255, 255, 255, 38)"
CORAL_PRIMARY = "#ff6e7f"
BLUE_LINK = "#bfe9ff"
GREEN_OK = "#34d399"
RED_ERR = "#f87171"
TEXT_PRIMARY = "#ffffff"
TEXT_MUTED = "rgba(255, 255, 255, 160)"
TEXT_SUB = "rgba(255, 255, 255, 110)"


def paint_sunset_background(painter: QPainter, rect: QRect) -> None:
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(SUNSET_TOP))
    grad.setColorAt(0.5, QColor(SUNSET_MID))
    grad.setColorAt(1.0, QColor(SUNSET_BOT))
    painter.fillRect(rect, grad)


GLOBAL_QSS = """
QMainWindow { background: transparent; }
QWidget#Sidebar {
    background: rgba(20, 20, 30, 200);
    border-right: 1px solid rgba(255, 255, 255, 30);
}
QWidget#GlassCard {
    background: rgba(20, 20, 30, 200);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 16px;
}
QPushButton#PrimaryButton {
    background: #ff6e7f;
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #ff7e8c; }
QPushButton#PrimaryButton:pressed { background: #e85e6f; }
QPushButton#SecondaryButton {
    background: transparent;
    color: #bfe9ff;
    border: 1px solid rgba(255, 255, 255, 60);
    border-radius: 10px;
    padding: 8px 16px;
}
QPushButton#SecondaryButton:hover { background: rgba(255, 255, 255, 20); }
QCheckBox { color: #ffffff; spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px;
    border-radius: 4px;
    border: 1px solid rgba(255, 255, 255, 60);
    background: transparent;
}
QCheckBox::indicator:checked {
    background: #ff6e7f;
    border: 1px solid #ff6e7f;
}
QRadioButton { color: #ffffff; spacing: 6px; }
QRadioButton::indicator {
    width: 16px; height: 16px; border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 60);
    background: transparent;
}
QRadioButton::indicator:checked {
    background: #ff6e7f;
    border: 1px solid #ff6e7f;
}
QLineEdit {
    background: rgba(20, 20, 30, 200);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 8px;
    color: #ffffff;
    padding: 6px 10px;
}
QLabel { color: #ffffff; }
QListWidget {
    background: rgba(20, 20, 30, 200);
    border: 1px solid rgba(255, 255, 255, 38);
    border-radius: 8px;
    color: #ffffff;
    padding: 4px;
}
QListWidget::item:selected { background: rgba(255, 110, 127, 100); }
QStatusBar { background: transparent; color: rgba(255, 255, 255, 180); }
"""
