"""GestureTutorialDialog — 7-step modal walkthrough.

Pops the first time the user enters the gesture page after starting the
engine (or manually via the "重看教学" button). Each step shows one of
the seven default gestures and waits up to 15s for the user to perform it.
Recognized → mark DONE → 1.5s auto-advance. Timeout → mark SKIPPED → next.

Side effects:
  * On open: saves bridge.teaching_mode, sets it to True.
  * On close: restores teaching_mode; if user reached step 7, sets
    cfg.tutorial_done=True and calls bridge.save().
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QFrame,
)

from pc_gesture.config import GESTURES


# Per-gesture display metadata (icon + Chinese name + one-line description).
# Mirrors the dict already used in gesture_page.py but kept local so the
# dialog can be moved/imported independently.
_TUTORIAL_META = {
    "FIST":         ("✊", "握拳",    "四指卷起，拇指压在食指外侧"),
    "PALM":         ("🖐", "张掌",    "五指全部伸直，掌心朝镜头"),
    "POINTING_UP":  ("☝", "食指上",  "只伸食指，其它四指卷起"),
    "THUMBS_UP":    ("👍", "竖拇指",  "拇指指向上方，其它四指卷起"),
    "THUMBS_DOWN":  ("👎", "拇指向下","拇指指向下方，其它四指卷起"),
    "SWIPE_LEFT":   ("◀", "挥左",    "张掌，手腕快速向左移"),
    "SWIPE_RIGHT":  ("▶", "挥右",    "张掌，手腕快速向右移"),
}

_STEP_TIMEOUT_MS = 15000        # 15s per step
_AUTO_ADVANCE_MS = 1500         # recognized → wait 1.5s before next step
_FINAL_CLOSE_MS = 800           # all DONE → 0.8s before dialog closes
_POLL_INTERVAL_MS = 150         # bridge.recent_gestures() poll cadence


class GestureTutorialDialog(QDialog):
    def __init__(self, *, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = bridge.cfg

        # ---- save & flip teaching_mode (auto-restore on close) ----
        self._prev_teaching_mode = bool(bridge.teaching_mode)
        bridge.set_teaching_mode(True)

        # ---- state ----
        self._step = 0                         # 0..len(GESTURES)-1
        self._step_results: list[str] = []     # "DONE" or "SKIPPED" per step
        self._last_seen_ts: float = 0.0        # for polling new recognitions
        self._step_started_at: float = time.monotonic()

        # ---- window ----
        self.setWindowTitle("手势教学")
        self.setModal(True)
        self.resize(420, 360)
        self.setStyleSheet("background:#0f172a;color:#ffffff;")

        # ---- layout ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        self._header = QLabel()
        self._header.setStyleSheet("color:rgba(255,255,255,200);font-size:12px;")
        outer.addWidget(self._header)

        # Gesture card
        self._card = QFrame()
        self._card.setObjectName("GlassCard")
        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(20, 20, 20, 20)
        cl.setSpacing(8)
        self._card_icon = QLabel()
        self._card_icon.setStyleSheet("font-size:64px;")
        self._card_icon.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_icon)
        self._card_name = QLabel()
        self._card_name.setStyleSheet("font-size:20px;font-weight:600;")
        self._card_name.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_name)
        self._card_action = QLabel()
        self._card_action.setStyleSheet("color:rgba(255,255,255,180);font-size:12px;")
        self._card_action.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._card_action)
        self._card_desc = QLabel()
        self._card_desc.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        self._card_desc.setAlignment(Qt.AlignCenter)
        self._card_desc.setWordWrap(True)
        cl.addWidget(self._card_desc)
        outer.addWidget(self._card)

        # Progress bar (15s countdown for current step)
        self._progress = QProgressBar()
        self._progress.setRange(0, _STEP_TIMEOUT_MS)
        self._progress.setValue(_STEP_TIMEOUT_MS)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setStyleSheet("QProgressBar{background:rgba(255,255,255,40);border:none;} QProgressBar::chunk{background:#22c55e;}")
        outer.addWidget(self._progress)

        self._status = QLabel("请做出手势")
        self._status.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        self._status.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_skip = QPushButton("跳过本步")
        self._btn_skip.clicked.connect(lambda: self._finish_step("SKIPPED"))
        btn_row.addWidget(self._btn_skip)
        self._btn_end = QPushButton("结束")
        self._btn_end.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_end)
        outer.addLayout(btn_row)

        # ---- timers ----
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_recognition)
        self._poll_timer.start()

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(lambda: self._finish_step("SKIPPED"))
        self._step_timer.start(_STEP_TIMEOUT_MS)

        # ---- render step 0 ----
        self._render_step()

    # ------------------------------------------------------------ step logic

    def _current_gesture(self) -> str:
        return GESTURES[self._step]

    def _render_step(self) -> None:
        g = self._current_gesture()
        icon, name, desc = _TUTORIAL_META[g]
        action = self._cfg.get_binding(g) or "（未绑定）"
        self._header.setText(f"第 {self._step + 1} / {len(GESTURES)} 步")
        self._card_icon.setText(icon)
        self._card_name.setText(name)
        self._card_action.setText(f"→ {action}")
        self._card_desc.setText(desc)
        self._status.setText("请做出手势（15 秒内）")
        self._step_started_at = time.monotonic()
        self._progress.setValue(_STEP_TIMEOUT_MS)
        self._step_timer.start(_STEP_TIMEOUT_MS)

    def _poll_recognition(self) -> None:
        """Watch bridge.recent_gestures() for the target gesture."""
        target = self._current_gesture()
        recent = self._bridge.recent_gestures()
        new = [r for r in recent if float(r.get("ts") or 0.0) > self._last_seen_ts]
        if not new:
            # tick down the countdown bar
            elapsed_ms = (time.monotonic() - self._step_started_at) * 1000.0
            remaining = max(0, int(_STEP_TIMEOUT_MS - elapsed_ms))
            self._progress.setValue(remaining)
            return
        # Mark last_seen_ts to newest entry
        self._last_seen_ts = max(float(r.get("ts") or 0.0) for r in new)
        if any(str(r.get("gesture") or "") == target for r in new):
            self._finish_step("DONE")

    def _finish_step(self, result: str) -> None:
        """Mark the current step result and advance / close."""
        self._step_results.append(result)
        self._step += 1
        if self._step >= len(GESTURES):
            # Final step done. Compute summary and accept.
            done = sum(1 for r in self._step_results if r == "DONE")
            skipped = len(GESTURES) - done
            if skipped == 0:
                self._status.setText("全部完成！🎉")
            else:
                self._status.setText(f"已跳过 {skipped} 个，可点「重看教学」再来")
            self._poll_timer.stop()
            self._step_timer.stop()
            # Mark tutorial_done only if user reached step 7 (regardless of
            # DONE/SKIPPED mix). User closing early (reject path) bypasses
            # this and doesn't write — boundary #5 of the spec.
            try:
                self._cfg.tutorial_done = True
                self._bridge.save()
            except Exception:
                pass
            QTimer.singleShot(_FINAL_CLOSE_MS, self.accept)
            return
        self._render_step()

    # ------------------------------------------------------------ cleanup

    def closeEvent(self, ev):
        # Restore teaching_mode on any close path (X button, reject, accept).
        try:
            self._bridge.set_teaching_mode(self._prev_teaching_mode)
        except Exception:
            pass
        try:
            self._poll_timer.stop()
            self._step_timer.stop()
        except Exception:
            pass
        super().closeEvent(ev)
