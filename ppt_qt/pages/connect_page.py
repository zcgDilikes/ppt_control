"""Connect page: QR code + pairing code + mobile status + start/stop service button."""
from __future__ import annotations

import io

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ppt_qt.widgets.glass_card import GlassCard
from ppt_qt.widgets.primary_button import PrimaryButton
from ppt_qt.widgets.status_pill import StatusPill


def _build_qr_pixmap(data: str, size: int = 220) -> QPixmap:
    """Build a QR code QPixmap for *data*. Falls back to a placeholder if
    the optional ``qrcode`` dependency is not available.
    """
    try:
        import qrcode  # type: ignore
    except Exception:
        return _placeholder_pixmap(size, "QR unavailable\n(qrcode not installed)")

    try:
        qr = qrcode.QRCode(box_size=6, border=1)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qimage = QImage()
        qimage.loadFromData(buf.getvalue(), "PNG")
        pix = QPixmap.fromImage(qimage)
        if pix.isNull():
            return _placeholder_pixmap(size, data)
        return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception:
        return _placeholder_pixmap(size, data)


def _placeholder_pixmap(size: int, text: str) -> QPixmap:
    """Render a fallback pixmap when QR generation fails."""
    pix = QPixmap(size, size)
    pix.fill(Qt.white)
    from PySide6.QtGui import QPainter, QColor, QFont

    painter = QPainter(pix)
    try:
        painter.setPen(QColor("#666"))
        painter.drawRect(0, 0, size - 1, size - 1)
        painter.setFont(QFont("Arial", 9))
        rect = pix.rect().adjusted(4, 4, -4, -4)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, text)
    finally:
        painter.end()
    return pix


class ConnectPage(QWidget):
    """Connection / pairing page.

    Layout: left GlassCard holds the QR code, big pairing code, and a mobile
    status pill. Right side exposes the primary "启动服务" / "停止服务" button
    driven by :py:meth:`set_running`.
    """

    def __init__(
        self,
        *,
        room_id: str,
        on_toggle_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self._room_id = str(room_id)
        self._on_toggle_service = on_toggle_service

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ---- Left card: QR + pairing code + mobile status ---------------
        left_card = GlassCard(self)
        left_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left = QVBoxLayout(left_card)
        left.setContentsMargins(28, 28, 28, 28)
        left.setSpacing(14)

        title = QLabel("扫码连接", left_card)
        title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        left.addWidget(title)

        self._qr_label = QLabel(left_card)
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setFixedSize(240, 240)
        self._qr_label.setStyleSheet(
            "background:#ffffff;border-radius:12px;padding:8px;"
        )
        self._qr_label.setPixmap(_build_qr_pixmap(self._room_id, size=224))
        left.addWidget(self._qr_label, 0, Qt.AlignHCenter)

        self._code_label = QLabel(self._room_id, left_card)
        self._code_label.setAlignment(Qt.AlignCenter)
        code_font = QFont()
        code_font.setPointSize(36)
        code_font.setBold(True)
        self._code_label.setFont(code_font)
        self._code_label.setStyleSheet(
            "color:#ffffff;letter-spacing:6px;padding:4px 0;"
        )
        left.addWidget(self._code_label, 0, Qt.AlignHCenter)

        hint = QLabel("在手机端 App 输入配对码或扫描二维码", left_card)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        left.addWidget(hint)

        left.addStretch(1)

        # Mobile status pill (small inline widget).
        self._mobile_pill = StatusPill(
            status_text="未连接",
            button_text="",
            parent=left_card,
        )
        self._mobile_pill.set_ok(False)
        left.addWidget(self._mobile_pill, 0, Qt.AlignHCenter)

        root.addWidget(left_card, 1)

        # ---- Right column: service control ------------------------------
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)

        status_card = GlassCard(self)
        status_card.setFixedWidth(260)
        sc = QVBoxLayout(status_card)
        sc.setContentsMargins(20, 20, 20, 20)
        sc.setSpacing(10)

        sc_title = QLabel("服务状态", status_card)
        sc_title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        sc.addWidget(sc_title)

        self._status_text = QLabel("服务未启动", status_card)
        self._status_text.setStyleSheet("color:rgba(255,255,255,180);font-size:12px;")
        self._status_text.setWordWrap(True)
        sc.addWidget(self._status_text)

        self._toggle_btn = PrimaryButton("启动服务", status_card)
        if on_toggle_service is not None:
            self._toggle_btn.clicked.connect(on_toggle_service)
        sc.addWidget(self._toggle_btn)

        right.addWidget(status_card, 0, Qt.AlignTop)
        right.addStretch(1)

        root.addLayout(right, 0)

        self.set_running(False)
        self.set_mobile_online(False)

    # -- public API -------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Update the human-readable service status line."""
        self._status_text.setText(text)

    def set_running(self, running: bool) -> None:
        """Toggle the service state: button label and status text."""
        if running:
            self._toggle_btn.setText("停止服务")
            self._status_text.setText("服务运行中")
        else:
            self._toggle_btn.setText("启动服务")
            self._status_text.setText("服务未启动")

    def set_mobile_online(self, online: bool) -> None:
        """Toggle the mobile connection pill."""
        if online:
            self._mobile_pill.set_status("已就绪")
            self._mobile_pill.set_ok(True)
        else:
            self._mobile_pill.set_status("未连接")
            self._mobile_pill.set_ok(False)
