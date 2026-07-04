"""Transfers page: list of received files with reveal/open-folder actions."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ppt_qt.widgets.glass_card import GlassCard
from ppt_qt.widgets.primary_button import PrimaryButton, SecondaryButton


def _format_ts(ts: float) -> str:
    """Format an epoch-seconds timestamp as ``MM-DD HH:MM``."""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
    except (OSError, OverflowError, ValueError, TypeError):
        return "--/-- --:--"


class TransfersPage(QWidget):
    """Transfers log page.

    Displays a :class:`QListWidget` of received files, each entry formatted as
    ``"MM-DD HH:MM  filename"``. Two action buttons let the user reveal the
    selected file in its folder (``on_reveal``) or open the save directory
    (``on_open_dir``).
    """

    def __init__(
        self,
        *,
        on_reveal: Callable[[Optional[int]], None],
        on_open_dir: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_reveal = on_reveal
        self._on_open_dir = on_open_dir

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ---- Header card ---------------------------------------------
        header_card = GlassCard(self)
        header_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        hc = QVBoxLayout(header_card)
        hc.setContentsMargins(28, 24, 28, 24)
        hc.setSpacing(6)

        title = QLabel("传输记录", header_card)
        title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        hc.addWidget(title)

        hint = QLabel("手机端推送过来的文件列表", header_card)
        hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        hc.addWidget(hint)

        root.addWidget(header_card)

        # ---- List card -----------------------------------------------
        list_card = GlassCard(self)
        list_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lc = QVBoxLayout(list_card)
        lc.setContentsMargins(28, 24, 28, 24)
        lc.setSpacing(12)

        list_title = QLabel("已接收文件", list_card)
        list_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        lc.addWidget(list_title)

        self._list = QListWidget(list_card)
        self._list.setUniformItemSizes(True)
        self._list.setAlternatingRowColors(True)
        self._list.setMinimumSize(QSize(320, 220))
        self._list.setStyleSheet(
            "QListWidget{background:rgba(255,255,255,20);"
            "color:#ffffff;border:1px solid rgba(255,255,255,40);"
            "border-radius:8px;padding:6px;}"
            "QListWidget::item{padding:6px 8px;}"
            "QListWidget::item:selected{background:rgba(255,255,255,60);"
            "color:#ffffff;}"
        )
        lc.addWidget(self._list, 1)

        root.addWidget(list_card, 1)

        # ---- Action buttons ------------------------------------------
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)

        self._reveal_btn = PrimaryButton("在文件夹中显示所选", self)
        self._reveal_btn.setEnabled(False)
        actions.addWidget(self._reveal_btn)

        self._open_dir_btn = SecondaryButton("打开保存目录", self)
        actions.addWidget(self._open_dir_btn)

        actions.addStretch(1)
        root.addLayout(actions)

        # ---- Wire signals --------------------------------------------
        self._reveal_btn.clicked.connect(self._handle_reveal)
        self._open_dir_btn.clicked.connect(self._handle_open_dir)
        self._list.itemSelectionChanged.connect(self._sync_reveal_enabled)
        self._list.itemDoubleClicked.connect(lambda _item: self._handle_reveal())

    # -- public API -------------------------------------------------------

    def set_records(self, records: list[dict]) -> None:
        """Refresh the list with a new batch of *records*.

        Each record is a ``dict`` with keys ``name``, ``path``, and ``ts``
        (``ts`` is float seconds since epoch). Records are displayed in the
        order received.
        """
        self._list.clear()
        if not records:
            placeholder = QListWidgetItem("(暂无传输记录)")
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)
            self._sync_reveal_enabled()
            return

        for rec in records:
            if not isinstance(rec, dict):
                continue
            name = str(rec.get("name", "") or "")
            ts = rec.get("ts", 0.0)
            label = f"{_format_ts(ts)}  {name}".rstrip()
            item = QListWidgetItem(label)
            path = rec.get("path", "")
            if path:
                item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path) if path else name)
            self._list.addItem(item)

        self._list.setCurrentRow(0)
        self._sync_reveal_enabled()

    # -- internals --------------------------------------------------------

    def _sync_reveal_enabled(self) -> None:
        """Enable the reveal button only when a real row is selected."""
        item = self._list.currentItem()
        enabled = bool(item is not None and (item.flags() & Qt.ItemIsSelectable))
        self._reveal_btn.setEnabled(enabled)

    def _selected_index(self) -> int:
        """Return the current row index, or ``-1`` when nothing is selected."""
        row = self._list.currentRow()
        return int(row) if row >= 0 else -1

    def _handle_reveal(self) -> None:
        idx = self._selected_index()
        if idx < 0:
            return
        if self._on_reveal is not None:
            self._on_reveal(idx)

    def _handle_open_dir(self) -> None:
        if self._on_open_dir is not None:
            self._on_open_dir()
