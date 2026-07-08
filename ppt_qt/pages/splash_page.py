"""SplashPage: brief 4-stage loading splash with progress ring.

Per plan §2.3:
  * QFrame with progress ring (QProgressBar) + status label.
  * 4 stages: importing → loading_model → init_camera → ready.
  * Caller invokes ``update_progress(stage, percent)`` from the async
    loader. ``ready`` stage signals completion so the caller can swap
    the splash out for the main window.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QLabel, QProgressBar,
)

# Stage names (callers pass these into update_progress)
STAGE_IMPORTING = "importing"
STAGE_LOADING_MODEL = "loading_model"
STAGE_INIT_CAMERA = "init_camera"
STAGE_READY = "ready"

# Display text per stage (per plan §2.3)
_STAGE_TEXTS = {
    STAGE_IMPORTING: "加载核心库…",
    STAGE_LOADING_MODEL: "加载手部模型…",
    STAGE_INIT_CAMERA: "初始化摄像头…",
    STAGE_READY: "完成",
}

# Stage → progress percent (each stage 25%; ready = 100)
_STAGE_PERCENTS = {
    STAGE_IMPORTING: 25,
    STAGE_LOADING_MODEL: 50,
    STAGE_INIT_CAMERA: 75,
    STAGE_READY: 100,
}


class SplashPage(QFrame):
    """Brief 4-stage splash screen widget.

    Emits ``finished`` when the ``ready`` stage is reached, so callers
    can swap to the main window without polling.
    """

    # Emitted once ``update_progress(STAGE_READY, ...)`` is called.
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SplashPage")
        self.setMinimumSize(420, 280)
        self.setStyleSheet(
            "QFrame#SplashPage {"
            "background:#0f172a;color:#f1f5f9;border-radius:12px;"
            "}"
            "QLabel {color:#f1f5f9;}"
            "QProgressBar {"
            "border:2px solid #334155;border-radius:8px;"
            "background:#1e293b;text-align:center;color:#f1f5f9;"
            "height:24px;"
            "}"
            "QProgressBar::chunk {"
            "background:#22c55e;border-radius:6px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        self._title = QLabel("PPT 遥控")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            "color:#f1f5f9;font-size:22px;font-weight:700;"
        )
        layout.addWidget(self._title)

        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(True)
        self._bar.setFormat("%p%")
        layout.addWidget(self._bar)

        self._status = QLabel(_STAGE_TEXTS[STAGE_IMPORTING])
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color:#cbd5e1;font-size:13px;")
        layout.addWidget(self._status)

        layout.addStretch(1)

        self._finished_emitted = False

    # -------------------------------------------------------------- public

    def update_progress(self, stage: str, percent: int | None = None) -> None:
        """Advance the progress ring + status text.

        ``percent`` is optional; if omitted, the canonical percent for the
        given stage is used. Final stage (``ready``) emits ``finished``.
        """
        if stage not in _STAGE_TEXTS:
            raise ValueError(f"unknown stage: {stage!r}")
        if percent is None:
            percent = _STAGE_PERCENTS[stage]
        self._bar.setValue(int(percent))
        self._status.setText(_STAGE_TEXTS[stage])
        if stage == STAGE_READY and not self._finished_emitted:
            self._finished_emitted = True
            self.finished.emit()

    # ----- test / introspection helpers (no production dependencies) ----

    @property
    def percent(self) -> int:
        """Current progress percent (0-100)."""
        return int(self._bar.value())

    @property
    def status_text(self) -> str:
        """Current status label text."""
        return self._status.text()