"""A simple QWidget that paints the sunset gradient background.

Centralising the paintEvent here avoids the ``central.paintEvent = ...`` monkey
patch the composition root previously used.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ppt_qt.theme import paint_sunset_background


class BackgroundWidget(QWidget):
    """QWidget subclass that paints the sunset gradient in its paintEvent."""

    def paintEvent(self, ev) -> None:  # noqa: N802 - Qt naming
        from PySide6.QtGui import QPainter

        p = QPainter(self)
        try:
            paint_sunset_background(p, self.rect())
        finally:
            p.end()