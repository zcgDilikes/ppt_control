from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QColor, QPainterPath
import time

THROTTLE_MS = 36


class SpotlightOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._cx = 0.5
        self._cy = 0.5
        self._hw = 0.075
        self._hh = 0.06
        self._last = 0.0
        self._pending = False

    def apply(self, cx, cy, hw, hh):
        self._cx, self._cy, self._hw, self._hh = cx, cy, hw, hh
        now = time.monotonic()
        if (now - self._last) * 1000 >= THROTTLE_MS:
            self._paint_now()
        elif not self._pending:
            self._pending = True
            QTimer.singleShot(THROTTLE_MS, self._paint_now)

    def _paint_now(self):
        self._last = time.monotonic()
        self._pending = False
        self.update()

    def hide_overlay(self):
        self.hide()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(0, 0, 0, 168))
        w, h = self.width(), self.height()
        cx, cy = self._cx * w, self._cy * h
        r = min(self._hw * w, self._hh * h)
        path = QPainterPath()
        path.addRect(self.rect())
        inner = QPainterPath()
        inner.addEllipse(cx - r, cy - r, 2 * r, 2 * r)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillPath(path.subtracted(inner), Qt.transparent)
        p.end()