"""Connect page: QR + pairing code + mobile status + PC stats.

Layout (single GlassCard):
  - 标题 + 二维码 + 配对码 + 提示 + 移动端状态 pill
  - 电脑状态 (CPU / 内存 / 硬盘)，每 1.5 秒刷新

启动/停止按钮只在顶部 StatusPill；本页不再重复按钮。
"""
from __future__ import annotations

import io
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QImage, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from ppt_qt.widgets.glass_card import GlassCard
from ppt_qt.widgets.status_pill import StatusPill


# ---------- QR 工具 -------------------------------------------------------

def _build_qr_pixmap(data: str, size: int = 220) -> QPixmap:
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
    pix = QPixmap(size, size)
    pix.fill(Qt.white)
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


# ---------- 电脑状态 卡片 --------------------------------------------------

def _fmt_bytes(n: int) -> str:
    """Human-readable bytes (e.g. 16.4 GB). n 是字节数。"""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _read_pc_stats() -> dict:
    """Return CPU%, RAM (used, total, percent), Disk (used, total, percent).

    Returns zeros if psutil is missing so the UI still renders.
    """
    try:
        import psutil  # type: ignore
    except Exception:
        return {"cpu": 0, "ram_used": 0, "ram_total": 0, "ram_pct": 0,
                "disk_used": 0, "disk_total": 0, "disk_pct": 0}
    try:
        cpu = float(psutil.cpu_percent(interval=None))
    except Exception:
        cpu = 0.0
    try:
        vm = psutil.virtual_memory()
        ram_used, ram_total, ram_pct = vm.used, vm.total, float(vm.percent)
    except Exception:
        ram_used = ram_total = 0
        ram_pct = 0.0
    try:
        # C: 盘或当前工作目录所在盘
        path = os.path.abspath(os.sep)
        du = psutil.disk_usage(path)
        disk_used, disk_total, disk_pct = du.used, du.total, float(du.percent)
    except Exception:
        disk_used = disk_total = 0
        disk_pct = 0.0
    return {
        "cpu": cpu,
        "ram_used": ram_used, "ram_total": ram_total, "ram_pct": ram_pct,
        "disk_used": disk_used, "disk_total": disk_total, "disk_pct": disk_pct,
    }


def _bar_color(pct: float) -> str:
    """Color-code load: green <60, yellow 60-85, red >85."""
    if pct < 60:
        return "#34d399"
    if pct < 85:
        return "#fbbf24"
    return "#f87171"


# ---------- 主控件 --------------------------------------------------------

class ConnectPage(QWidget):
    """Connection / pairing / PC-stats page."""

    def __init__(
        self,
        *,
        room_id: str,
        on_toggle_service=None,  # kept for back-compat; no longer used here
        parent=None,
    ):
        super().__init__(parent)
        self._room_id = str(room_id)
        self._on_toggle_service = on_toggle_service  # unused, but accepted
        self._pc_timer = None
        self._has_psutil = self._detect_psutil()

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ---- Single GlassCard: QR + pairing code + mobile status + PC stats ---
        card = GlassCard(self)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        v = QVBoxLayout(card)
        v.setContentsMargins(28, 24, 28, 24)
        v.setSpacing(10)

        # 标题
        title = QLabel("扫码连接", card)
        title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        v.addWidget(title)

        # QR + 配对码 横排
        qr_row = QHBoxLayout()
        qr_row.setSpacing(24)
        qr_row.setAlignment(Qt.AlignHCenter)

        self._qr_label = QLabel(card)
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setFixedSize(220, 220)
        self._qr_label.setStyleSheet(
            "background:#ffffff;border-radius:12px;padding:6px;"
        )
        self._qr_label.setPixmap(_build_qr_pixmap(self._room_id, size=208))
        qr_row.addWidget(self._qr_label, 0, Qt.AlignVCenter)

        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        self._code_label = QLabel(self._room_id, card)
        self._code_label.setAlignment(Qt.AlignCenter)
        code_font = QFont()
        code_font.setPointSize(36)
        code_font.setBold(True)
        self._code_label.setFont(code_font)
        self._code_label.setStyleSheet(
            "color:#ffffff;letter-spacing:6px;padding:4px 0;"
        )
        right_col.addWidget(self._code_label, 0, Qt.AlignHCenter)

        hint = QLabel("在手机端输入配对码或扫描二维码", card)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        right_col.addWidget(hint, 0, Qt.AlignHCenter)

        # 移动端状态 pill（紧贴配对码下方）
        self._mobile_pill = StatusPill(
            status_text="未连接", button_text="", parent=card,
        )
        self._mobile_pill.set_ok(False)
        right_col.addSpacing(6)
        right_col.addWidget(self._mobile_pill, 0, Qt.AlignHCenter)

        right_col.addStretch(1)
        qr_row.addLayout(right_col, 1)
        v.addLayout(qr_row)

        # ---- 电脑状态 区域 -------------------------------------------------
        sep = QLabel(card)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:rgba(255,255,255,40);")
        v.addSpacing(4)
        v.addWidget(sep)
        v.addSpacing(8)

        pc_title = QLabel("电脑状态", card)
        pc_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        v.addWidget(pc_title)

        # 3 个 stat 列：CPU / 内存 / 硬盘
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self._stat_widgets = {}
        for key, label in (("cpu", "CPU"), ("ram", "内存"), ("disk", "硬盘")):
            stat_widget, parts = self._build_stat_card(card, label)
            stats_row.addWidget(stat_widget, 1)
            self._stat_widgets[key] = parts
        v.addLayout(stats_row)

        v.addStretch(1)

        # 电脑状态不可用时的提示
        if not self._has_psutil:
            for stat in self._stat_widgets.values():
                stat["value"].setText("psutil 未安装")

        # ---- 刷新定时器 ---------------------------------------------------
        self._pc_timer = QTimer(self)
        self._pc_timer.setInterval(1500)
        self._pc_timer.timeout.connect(self._refresh_pc_stats)
        self._pc_timer.start()
        self._refresh_pc_stats()  # 立即刷一次

        root.addWidget(card, 1)

        self.set_running(False)
        self.set_mobile_online(False)

    # ----------------------------------------------------------------------
    # stat card 构造
    # ----------------------------------------------------------------------
    def _build_stat_card(self, parent: QWidget, label: str) -> tuple:
        stat = QWidget(parent)
        stat.setObjectName("StatCard")
        stat.setStyleSheet(
            "QWidget#StatCard {"
            "  background: rgba(255,255,255,18);"
            "  border: 1px solid rgba(255,255,255,30);"
            "  border-radius: 10px;"
            "}"
        )
        lay = QVBoxLayout(stat)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        lbl = QLabel(label, stat)
        lbl.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;border:none;")
        lay.addWidget(lbl)

        value = QLabel("—", stat)
        value.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;border:none;")
        lay.addWidget(value)

        bar = QProgressBar(stat)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(
            "QProgressBar {"
            "  background: rgba(255,255,255,40);"
            "  border: none; border-radius: 3px;"
            "}"
            "QProgressBar::chunk {"
            "  background-color: #34d399;"
            "  border-radius: 3px;"
            "}"
        )
        lay.addWidget(bar)

        return stat, {"value": value, "bar": bar}

    def _refresh_pc_stats(self) -> None:
        stats = _read_pc_stats()
        for key, pct, used, total in (
            ("cpu", stats["cpu"], None, None),
            ("ram", stats["ram_pct"], stats["ram_used"], stats["ram_total"]),
            ("disk", stats["disk_pct"], stats["disk_used"], stats["disk_total"]),
        ):
            w = self._stat_widgets.get(key)
            if w is None:
                continue
            try:
                pct_int = int(round(pct))
            except Exception:
                pct_int = 0
            w["bar"].setValue(max(0, min(100, pct_int)))
            w["bar"].setStyleSheet(
                "QProgressBar {"
                "  background: rgba(255,255,255,40);"
                "  border: none; border-radius: 3px;"
                "}"
                "QProgressBar::chunk {"
                f"  background-color: {_bar_color(pct)};"
                "  border-radius: 3px;"
                "}"
            )
            if used is None:
                w["value"].setText(f"{pct_int}%")
            else:
                w["value"].setText(f"{_fmt_bytes(used)} / {_fmt_bytes(total)}  ({pct_int}%)")

    @staticmethod
    def _detect_psutil() -> bool:
        try:
            import psutil  # type: ignore
            return True
        except Exception:
            return False

    # -- public API --------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Kept for back-compat; the page no longer renders service status
        text. The status pill at the top of the window is the single source
        of truth for service state."""
        return

    def set_running(self, running: bool) -> None:
        """No-op for back-compat: button lives in the global StatusPill."""
        return

    def set_mobile_online(self, online: bool) -> None:
        """Toggle the mobile connection pill."""
        if online:
            self._mobile_pill.set_status("已就绪")
            self._mobile_pill.set_ok(True)
        else:
            self._mobile_pill.set_status("未连接")
            self._mobile_pill.set_ok(False)
