"""Gesture control page: lifecycle buttons + mode/preview/mirror/pairing toggles.

Wraps :class:`ppt_core.gesture_bridge.GestureBridge` and lets the user:

* Start / stop the gesture engine (``bridge.start()`` / ``bridge.stop()``).
* Toggle ``preview_only`` so the camera preview shows without dispatching commands.
* Switch between ``single`` (one-operator) and ``dual`` (two-hands collaborative) modes.
* Mirror the camera frame (``mirror`` flag).
* Swap A/B role assignment at runtime (``dual_roles_swapped`` → ``bridge.swap_roles``).
* Begin a fresh dual-hand pairing or reset the current one
  (``bridge.start_pairing()`` / ``bridge.reset_pairing()``).

Any toggle / radio change writes back to ``bridge.engine.cfg.raw[...]`` and
calls ``bridge.save()`` so the choice is persisted. The page also exposes
``set_status(text)`` / ``set_fps(fps)`` so the host can stream live updates
from the engine's callbacks onto the page.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ppt_qt.widgets.glass_card import GlassCard
from ppt_qt.widgets.primary_button import PrimaryButton, SecondaryButton


class GesturePage(QWidget):
    """Gesture control panel bound to a :class:`GestureBridge` instance."""

    # Raw config keys — kept here so the page owns its slice of the JSON schema.
    _KEY_PREVIEW = "preview_only"
    _KEY_MODE = "operator_mode"
    _KEY_MIRROR = "mirror"
    _KEY_SWAP = "dual_roles_swapped"

    def __init__(self, *, bridge, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._bridge = bridge

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # ---- Header card -------------------------------------------------
        header = GlassCard(self)
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        hc = QVBoxLayout(header)
        hc.setContentsMargins(28, 24, 28, 24)
        hc.setSpacing(6)

        title = QLabel("手势控制", header)
        title.setStyleSheet("color:#ffffff;font-size:14px;font-weight:600;")
        hc.addWidget(title)

        hint = QLabel("通过摄像头识别手势来操作幻灯片", header)
        hint.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        hc.addWidget(hint)

        root.addWidget(header)

        # ---- Mode toggles card ------------------------------------------
        mode_card = GlassCard(self)
        mode_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        mc = QVBoxLayout(mode_card)
        mc.setContentsMargins(28, 24, 28, 24)
        mc.setSpacing(10)

        mode_title = QLabel("识别模式", mode_card)
        mode_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        mc.addWidget(mode_title)

        # preview_only
        self._cb_preview = QCheckBox("仅预览（不触发操作）", mode_card)
        self._cb_preview.setStyleSheet(
            "color:#ffffff;font-size:13px;spacing:8px;padding:4px 0;"
        )
        mc.addWidget(self._cb_preview)

        # operator_mode radios (single / dual)
        radio_row = QHBoxLayout()
        radio_row.setContentsMargins(0, 0, 0, 0)
        radio_row.setSpacing(18)

        self._rb_single = QRadioButton("单人主控", mode_card)
        self._rb_dual = QRadioButton("双人协作", mode_card)
        for rb in (self._rb_single, self._rb_dual):
            rb.setStyleSheet("color:#ffffff;font-size:13px;spacing:6px;")
            radio_row.addWidget(rb)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._rb_single)
        self._mode_group.addButton(self._rb_dual)

        radio_row.addStretch(1)
        mc.addLayout(radio_row)

        # mirror
        self._cb_mirror = QCheckBox("镜像画面", mode_card)
        self._cb_mirror.setStyleSheet(
            "color:#ffffff;font-size:13px;spacing:8px;padding:4px 0;"
        )
        mc.addWidget(self._cb_mirror)

        # dual_roles_swapped
        self._cb_swap = QCheckBox("交换 A/B 职责", mode_card)
        self._cb_swap.setStyleSheet(
            "color:#ffffff;font-size:13px;spacing:8px;padding:4px 0;"
        )
        mc.addWidget(self._cb_swap)

        mc.addStretch(1)
        root.addWidget(mode_card)

        # ---- Actions card -----------------------------------------------
        actions_card = GlassCard(self)
        actions_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        ac = QVBoxLayout(actions_card)
        ac.setContentsMargins(28, 24, 28, 24)
        ac.setSpacing(10)

        actions_title = QLabel("控制", actions_card)
        actions_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        ac.addWidget(actions_title)

        engine_row = QHBoxLayout()
        engine_row.setContentsMargins(0, 0, 0, 0)
        engine_row.setSpacing(10)

        self._start_btn = PrimaryButton("启动手势", actions_card)
        engine_row.addWidget(self._start_btn)

        self._stop_btn = SecondaryButton("停止", actions_card)
        engine_row.addWidget(self._stop_btn)
        engine_row.addStretch(1)

        ac.addLayout(engine_row)

        pair_row = QHBoxLayout()
        pair_row.setContentsMargins(0, 0, 0, 0)
        pair_row.setSpacing(10)

        self._pair_btn = PrimaryButton("开始双人配对", actions_card)
        pair_row.addWidget(self._pair_btn)

        self._re_pair_btn = SecondaryButton("重新配对", actions_card)
        pair_row.addWidget(self._re_pair_btn)
        pair_row.addStretch(1)

        ac.addLayout(pair_row)

        root.addWidget(actions_card)

        # ---- Status card -------------------------------------------------
        status_card = GlassCard(self)
        status_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sc = QVBoxLayout(status_card)
        sc.setContentsMargins(28, 24, 28, 24)
        sc.setSpacing(8)

        status_title = QLabel("运行状态", status_card)
        status_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        sc.addWidget(status_title)

        self._status_label = QLabel("尚未启动", status_card)
        self._status_label.setStyleSheet("color:rgba(255,255,255,180);font-size:12px;")
        self._status_label.setWordWrap(True)
        sc.addWidget(self._status_label)

        fps_row = QHBoxLayout()
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.setSpacing(8)

        fps_key = QLabel("FPS：", status_card)
        fps_key.setStyleSheet("color:rgba(255,255,255,160);font-size:12px;")
        fps_row.addWidget(fps_key)

        self._fps_label = QLabel("--", status_card)
        self._fps_label.setStyleSheet(
            "color:#ffffff;font-size:12px;font-weight:600;"
        )
        fps_row.addWidget(self._fps_label)
        fps_row.addStretch(1)

        sc.addLayout(fps_row)
        sc.addStretch(1)
        root.addWidget(status_card, 1)

        # ---- Wire signals -----------------------------------------------
        self._cb_preview.toggled.connect(self._on_preview_toggled)
        self._rb_single.toggled.connect(self._on_mode_toggled)
        self._rb_dual.toggled.connect(self._on_mode_toggled)
        self._cb_mirror.toggled.connect(self._on_mirror_toggled)
        self._cb_swap.toggled.connect(self._on_swap_toggled)

        self._start_btn.clicked.connect(self._on_start_clicked)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._pair_btn.clicked.connect(self._on_pair_clicked)
        self._re_pair_btn.clicked.connect(self._on_re_pair_clicked)

        # Populate widget state from the live (or freshly ensured) config.
        self._reload_from_engine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, text: str) -> None:
        """Update the status line (typically called from the engine thread)."""
        if not text:
            return
        self._status_label.setText(str(text))

    def set_fps(self, fps: float) -> None:
        """Update the FPS readout (typically called from the engine thread)."""
        try:
            value = float(fps)
        except (TypeError, ValueError):
            self._fps_label.setText("--")
            return
        if value <= 0.0:
            self._fps_label.setText("--")
        else:
            self._fps_label.setText(f"{value:.1f}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_engine(self):
        """Return the live engine, constructing it via the bridge if needed.

        The bridge lazily allocates ``GestureEngine`` on first use, so any
        page-side raw-config edit must guarantee it exists. We rely on the
        bridge's own ``_ensure`` for that — it is the only way to read
        ``engine.cfg.raw`` without a ``None`` engine.
        """
        return self._bridge._ensure()  # noqa: SLF001 — intentional internal use

    def _reload_from_engine(self) -> None:
        """Sync widget state from ``bridge.engine.cfg.raw``.

        Called once during construction. Any unknown mode value falls back to
        ``single`` so the page always reflects a valid selection.
        """
        eng = self._ensure_engine()
        raw = eng.cfg.raw

        def _block(callable_):
            for w in (
                self._cb_preview,
                self._rb_single,
                self._rb_dual,
                self._cb_mirror,
                self._cb_swap,
            ):
                w.blockSignals(True)
            try:
                callable_()
            finally:
                for w in (
                    self._cb_preview,
                    self._rb_single,
                    self._rb_dual,
                    self._cb_mirror,
                    self._cb_swap,
                ):
                    w.blockSignals(False)

        def _apply():
            self._cb_preview.setChecked(bool(raw.get(self._KEY_PREVIEW, False)))
            self._cb_mirror.setChecked(bool(raw.get(self._KEY_MIRROR, True)))
            self._cb_swap.setChecked(bool(raw.get(self._KEY_SWAP, False)))

            mode = str(raw.get(self._KEY_MODE, "single")).strip().lower()
            if mode == "dual":
                self._rb_dual.setChecked(True)
            else:
                self._rb_single.setChecked(True)

        _block(_apply)

    def _write_raw_and_save(self, key: str, value) -> None:
        """Write ``bridge.engine.cfg.raw[key] = value`` then ``bridge.save()``."""
        eng = self._ensure_engine()
        eng.cfg.raw[key] = value
        try:
            self._bridge.save()
        except Exception:
            # save() already swallows errors internally; this is just a belt.
            pass

    # ------------------------------------------------------------------
    # Slots: widgets → engine
    # ------------------------------------------------------------------

    def _on_preview_toggled(self, checked: bool) -> None:
        self._write_raw_and_save(self._KEY_PREVIEW, bool(checked))

    def _on_mode_toggled(self, _checked: bool) -> None:
        mode = "dual" if self._rb_dual.isChecked() else "single"
        self._write_raw_and_save(self._KEY_MODE, mode)

    def _on_mirror_toggled(self, checked: bool) -> None:
        self._write_raw_and_save(self._KEY_MIRROR, bool(checked))

    def _on_swap_toggled(self, checked: bool) -> None:
        # ``swap_roles`` already persists + reloads semantics — no extra save.
        try:
            self._bridge.swap_roles(bool(checked))
        except Exception:
            # Don't crash the UI if the bridge can't apply the swap right now.
            pass

    def _on_start_clicked(self) -> None:
        try:
            err = self._bridge.start()
        except Exception as ex:
            self.set_status(f"启动失败：{ex}")
            return
        if err:
            self.set_status(f"启动失败：{err}")
        else:
            self.set_status("手势识别运行中")

    def _on_stop_clicked(self) -> None:
        try:
            self._bridge.stop()
        except Exception as ex:
            self.set_status(f"停止失败：{ex}")
            return
        self.set_status("已停止")
        self.set_fps(0.0)

    def _on_pair_clicked(self) -> None:
        try:
            self._bridge.start_pairing()
        except Exception as ex:
            self.set_status(f"配对失败：{ex}")

    def _on_re_pair_clicked(self) -> None:
        try:
            self._bridge.reset_pairing()
        except Exception as ex:
            self.set_status(f"重置配对失败：{ex}")
