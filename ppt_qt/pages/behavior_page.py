"""Behavior settings page: post-action behaviors + default PPT path."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ppt_qt.widgets.glass_card import GlassCard
from ppt_qt.widgets.primary_button import PrimaryButton, SecondaryButton


class BehaviorPage(QWidget):
    """Page exposing post-action toggles and the default PPT file path.

    Any widget change rebuilds the full settings dict and forwards it to
    ``on_change``. The host (typically ``MainWindow``) decides whether to
    persist, broadcast, or just cache it.
    """

    # Keys we manage locally — kept in sync with ppt_core.settings.DEFAULT_SETTINGS.
    _KEYS = (
        "screenshot_open_folder",
        "transfer_open_folder",
        "transfer_open_ppt",
        "ppt_notes_enabled",
        "open_ppt_path",
    )

    def __init__(
        self,
        *,
        settings: dict,
        on_change: Callable[[dict], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_change = on_change
        # Working copy — never mutate the caller's dict in place.
        self._settings: dict = dict(settings)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ---- Behavior toggles card ------------------------------------
        toggles_card = GlassCard(self)
        toggles_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tc = QVBoxLayout(toggles_card)
        tc.setContentsMargins(28, 24, 28, 24)
        tc.setSpacing(10)

        title = QLabel("行为设置", toggles_card)
        title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        tc.addWidget(title)

        hint = QLabel("选择手机端操作完成后,电脑端的默认行为", toggles_card)
        hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        tc.addWidget(hint)

        self._cb_screenshot_folder = QCheckBox("截屏后打开文件夹", toggles_card)
        self._cb_transfer_folder = QCheckBox("传输非演示文稿时打开文件夹", toggles_card)
        self._cb_transfer_ppt = QCheckBox("传输演示文稿时自动打开", toggles_card)
        self._cb_notes = QCheckBox("演讲者模式", toggles_card)

        for cb in (
            self._cb_screenshot_folder,
            self._cb_transfer_folder,
            self._cb_transfer_ppt,
            self._cb_notes,
        ):
            cb.setStyleSheet(
                "color:#ffffff;font-size:13px;spacing:8px;padding:4px 0;"
            )
            tc.addWidget(cb)

        tc.addStretch(1)
        root.addWidget(toggles_card)

        # ---- Default PPT path card ------------------------------------
        path_card = GlassCard(self)
        path_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        pc = QVBoxLayout(path_card)
        pc.setContentsMargins(28, 24, 28, 24)
        pc.setSpacing(10)

        path_title = QLabel("默认演示文稿", path_card)
        path_title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        pc.addWidget(path_title)

        path_hint = QLabel("未指定文件时,传输演示文稿将打开该文件", path_card)
        path_hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        path_hint.setWordWrap(True)
        pc.addWidget(path_hint)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)

        self._path_edit = QLineEdit(path_card)
        self._path_edit.setPlaceholderText("选择 .ppt / .pptx 文件…")
        self._path_edit.setClearButtonEnabled(True)
        path_row.addWidget(self._path_edit, 1)

        self._browse_btn = PrimaryButton("浏览…", path_card)
        path_row.addWidget(self._browse_btn)

        self._clear_btn = SecondaryButton("清除", path_card)
        path_row.addWidget(self._clear_btn)

        pc.addLayout(path_row)
        root.addWidget(path_card)

        # ---- Wire up signals ------------------------------------------
        self._cb_screenshot_folder.toggled.connect(self._notify_change)
        self._cb_transfer_folder.toggled.connect(self._notify_change)
        self._cb_transfer_ppt.toggled.connect(self._notify_change)
        self._cb_notes.toggled.connect(self._notify_change)
        self._path_edit.textChanged.connect(self._on_path_edited)
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        self._clear_btn.clicked.connect(self._on_clear_clicked)

        # Initial population (without firing on_change).
        self.reload_from_model()

    # -- public API -------------------------------------------------------

    def reload_from_model(self) -> None:
        """Re-read values from the in-memory settings dict.

        Widgets are blocked while being updated so we don't fire on_change
        for every value we re-sync.
        """
        self._settings = dict(self._settings)  # shallow copy guard

        for widget, key in (
            (self._cb_screenshot_folder, "screenshot_open_folder"),
            (self._cb_transfer_folder, "transfer_open_folder"),
            (self._cb_transfer_ppt, "transfer_open_ppt"),
            (self._cb_notes, "ppt_notes_enabled"),
        ):
            widget.blockSignals(True)
            try:
                widget.setChecked(bool(self._settings.get(key, False)))
            finally:
                widget.blockSignals(False)

        self._path_edit.blockSignals(True)
        try:
            self._path_edit.setText(str(self._settings.get("open_ppt_path", "") or ""))
        finally:
            self._path_edit.blockSignals(False)

    # -- internals --------------------------------------------------------

    def _current_dict(self) -> dict:
        """Return a fresh dict with all keys populated from the current widget state."""
        return {
            "screenshot_open_folder": self._cb_screenshot_folder.isChecked(),
            "transfer_open_folder": self._cb_transfer_folder.isChecked(),
            "transfer_open_ppt": self._cb_transfer_ppt.isChecked(),
            "ppt_notes_enabled": self._cb_notes.isChecked(),
            "open_ppt_path": self._path_edit.text().strip(),
        }

    def _notify_change(self) -> None:
        payload = self._current_dict()
        self._settings = payload
        if self._on_change is not None:
            self._on_change(payload)

    def _on_path_edited(self, _text: str) -> None:
        self._notify_change()

    def _on_browse_clicked(self) -> None:
        start_dir = ""
        current = self._path_edit.text().strip()
        if current:
            try:
                p = Path(current)
                if p.is_file():
                    start_dir = str(p.parent)
                elif p.is_dir():
                    start_dir = str(p)
            except OSError:
                start_dir = ""

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择默认演示文稿",
            start_dir,
            "演示文稿 (*.ppt *.pptx);;所有文件 (*)",
        )
        if not path:
            return
        # setText fires textChanged → _notify_change → on_change, which is desired.
        self._path_edit.setText(path)

    def _on_clear_clicked(self) -> None:
        if self._path_edit.text():
            self._path_edit.clear()