"""Gesture control page: 7-slot binding editor / live trial / control buttons."""
from __future__ import annotations

import json
import os
import time
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
)

from pc_gesture.config import GESTURES, ACTIONS

# 手势显示：图标 + 中文名
_GESTURE_META = {
    "FIST":         ("✊", "握拳"),
    "PALM":         ("🖐", "张掌"),
    "POINTING_UP":  ("☝", "食指上"),
    "THUMBS_UP":    ("👍", "竖拇指"),
    "THUMBS_DOWN":  ("👎", "拇指向下"),
    "SWIPE_LEFT":   ("◀", "挥左"),
    "SWIPE_RIGHT":  ("▶", "挥右"),
}

# 动作下拉显示
_ACTION_LABEL = {
    "NEXT_PAGE":          "下一页",
    "PREV_PAGE":          "上一页",
    "FULL_SCREEN":        "从头放映",
    "FROM_CURRENT":       "从当前放映",
    "BLACK_SCREEN":       "黑屏",
    "WHITE_SCREEN":       "白屏",
    "EXIT":               "退出放映",
    "SCREENSHOT":         "截屏",
    "OPEN_PPT":           "启动PPT",
    "PC_WINDOW_MINIMIZE": "PC端最小化",
    "PC_WINDOW_RESTORE":  "PC端恢复",
}

# 反向：gesture -> 中文名
_GESTURE_NAME = {k: v[1] for k, v in _GESTURE_META.items()}


class GesturePage(QWidget):
    def __init__(self, *, bridge, on_status=None, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = bridge.cfg
        self._on_status = on_status
        self._history: List[Dict] = []
        self._current_gesture: Optional[str] = None

        # ---- frame snapshot 状态 ----
        self._last_hand_seen_at: float = 0.0   # 最近一次看到手的 wall-clock (currently unused; reserved for spec §3 boundary #3 timing)
        self._finger_state_prev: Dict[str, bool] = {}   # 上一帧手指状态,避免每帧重绘
        self._preview_scale: float = 1.0  # 自适应降级缩放系数

        # ---- 顶部工具栏(教学模式 + 查找 + 状态灯) ----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self._teaching_check = QCheckBox("教学模式（只识别不派发）")
        self._teaching_check.setChecked(bool(self._bridge.teaching_mode))
        self._teaching_check.toggled.connect(self._on_teaching_toggled)
        toolbar.addWidget(self._teaching_check, 0, Qt.AlignVCenter)
        toolbar.addStretch(1)
        # 三色状态灯
        self._status_light = QLabel()
        self._status_light.setFixedSize(20, 20)
        self._status_light.setStyleSheet(
            "background:#6b7280;border-radius:10px;border:2px solid #1f2937;"
        )
        toolbar.addWidget(self._status_light, 0, Qt.AlignVCenter)
        toolbar.addWidget(QLabel("查找:"), 0, Qt.AlignVCenter)
        self._query_combo = QComboBox()
        self._query_combo.addItem("（全部未绑定）", userData=None)
        for a in ACTIONS:
            self._query_combo.addItem(_ACTION_LABEL[a], userData=a)
        self._query_combo.currentIndexChanged.connect(self._refresh_query_hint)
        toolbar.addWidget(self._query_combo, 1)
        self._query_hint = QLabel("")
        self._query_hint.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        toolbar.addWidget(self._query_hint, 2)

        # ---- 主布局：左右两栏 ----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.addLayout(toolbar)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        columns.addWidget(self._build_left_column(), 5)
        columns.addWidget(self._build_right_column(), 5)
        outer.addLayout(columns, 1)

        # ---- 状态行 ----
        self._status_lbl = QLabel("未启动")
        self._status_lbl.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        outer.addWidget(self._status_lbl)

        # ---- 反查提示 ----
        self._refresh_query_hint()

        # ---- engine 回调(已有,不动) ----
        bridge._on_status = lambda t: self._on_bridge_status(t)
        bridge._on_fps = lambda f: self._on_bridge_fps(f)
        eng_now = bridge.engine
        if eng_now is not None:
            eng_now._on_status = bridge._on_status
            eng_now._on_fps = bridge._on_fps

        # ---- frame Signal 绑定 ----
        bridge.frame_signal.connect(self._on_frame_signal)

        # ---- 轮询兜底(150ms):试面板 + 三色灯 + 诊断面板(用于 Signal 失效) ----
        self._last_seen_ts = 0.0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._poll_bridge_gestures)
        self._poll_timer.start()
        # 单独一个 timer 兜底 _on_frame_signal
        self._frame_poll_timer = QTimer(self)
        self._frame_poll_timer.setInterval(150)
        self._frame_poll_timer.timeout.connect(self._poll_latest_snapshot)
        self._frame_poll_timer.start()

    # ----- 私有：构建左右两栏 -----
    def _build_left_column(self) -> QFrame:
        """Build the left column: embedded preview + status light + diagnostic panel."""
        col = QFrame()
        col.setObjectName("GlassCard")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        title = QLabel("📹 实时预览 + 诊断")
        title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        cl.addWidget(title)

        # 预览 QLabel,16:9 比例
        self._preview_label = QLabel("未启动")
        self._preview_label.setMinimumHeight(280)
        self._preview_label.setAlignment(Qt.AlignCenter)
        self._preview_label.setStyleSheet(
            "background:#0a0a0a;color:rgba(255,255,255,120);font-size:12px;"
            "border-radius:6px;"
        )
        cl.addWidget(self._preview_label, 1)

        # 诊断面板
        diag_card = QFrame()
        diag_card.setObjectName("GlassCard")
        dl = QVBoxLayout(diag_card)
        dl.setContentsMargins(10, 10, 10, 10)
        dl.setSpacing(4)
        diag_title = QLabel("诊断")
        diag_title.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;font-weight:600;")
        dl.addWidget(diag_title)
        # 各手势状态行
        self._diag_gesture_labels: Dict[str, QLabel] = {}
        for g in GESTURES:
            row = QHBoxLayout()
            row.setSpacing(6)
            ico, name = _GESTURE_META[g]
            ic = QLabel(ico)
            ic.setFixedWidth(20)
            ic.setStyleSheet("font-size:13px;")
            row.addWidget(ic, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:11px;")
            row.addWidget(name_lbl, 0, Qt.AlignVCenter)
            state_lbl = QLabel("—")
            state_lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;font-family:Consolas,monospace;")
            self._diag_gesture_labels[g] = state_lbl
            row.addWidget(state_lbl, 1, Qt.AlignVCenter)
            row.addStretch(1)
            dl.addLayout(row)
        # 手指状态灯
        sep = QLabel("手指:")
        sep.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;margin-top:6px;")
        dl.addWidget(sep)
        self._finger_lights: Dict[str, tuple] = {}
        finger_names = [("thumb", "拇指"), ("index", "食指"), ("middle", "中指"), ("ring", "无名指"), ("pinky", "小指")]
        for key, name in finger_names:
            row = QHBoxLayout()
            row.setSpacing(6)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:11px;")
            row.addWidget(name_lbl, 0, Qt.AlignVCenter)
            light_lbl = QLabel("○")
            light_lbl.setFixedWidth(16)
            light_lbl.setStyleSheet("color:#6b7280;font-size:14px;")
            row.addWidget(light_lbl, 0, Qt.AlignVCenter)
            state_lbl = QLabel("卷曲")
            state_lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
            row.addWidget(state_lbl, 0, Qt.AlignVCenter)
            row.addStretch(1)
            self._finger_lights[key] = (light_lbl, state_lbl)
            dl.addLayout(row)
        # 手位置 / 置信度 / slot
        self._hand_xy_lbl = QLabel("手位置: —")
        self._hand_xy_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._hand_xy_lbl)
        self._conf_lbl = QLabel("置信度: —")
        self._conf_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._conf_lbl)
        self._slot_lbl = QLabel("Slot: —")
        self._slot_lbl.setStyleSheet("color:rgba(255,255,255,150);font-size:11px;")
        dl.addWidget(self._slot_lbl)
        cl.addWidget(diag_card)

        return col

    def _build_right_column(self) -> QFrame:
        """Build the right column: cheat card + binding + trial + controls."""
        col = QFrame()
        col.setObjectName("GlassCard")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # ① 手势示图卡
        cheat_title = QLabel("① 手势示图卡")
        cheat_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        cl.addWidget(cheat_title)
        self._cheat_rows: Dict[str, QFrame] = {}
        for g in GESTURES:
            row = QFrame()
            row.setObjectName("CheatRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            rl.setSpacing(8)
            ico, name = _GESTURE_META[g]
            ico_lbl = QLabel(ico)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:16px;")
            rl.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-size:13px;")
            rl.addWidget(name_lbl, 0, Qt.AlignVCenter)
            action_lbl = QLabel("（未绑定）")
            action_lbl.setStyleSheet("color:rgba(255,255,255,160);font-size:11px;")
            rl.addWidget(action_lbl, 0, Qt.AlignVCenter)
            rl.addStretch(1)
            cl.addWidget(row)
            self._cheat_rows[g] = row
            row.__dict__["_action_lbl"] = action_lbl
        for g, row in self._cheat_rows.items():
            action = self._cfg.get_binding(g)
            label = _ACTION_LABEL.get(action, "（未绑定）") if action else "（未绑定）"
            row.__dict__["_action_lbl"].setText(f"→ {label}" if action else "（未绑定）")

        # ② 手势映射
        title1 = QLabel("② 手势映射")
        title1.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;margin-top:6px;")
        cl.addWidget(title1)
        self._binding_combos: Dict[str, QComboBox] = {}
        self._binding_rows: Dict[str, QFrame] = {}
        for g in GESTURES:
            row = QFrame()
            row.setObjectName("BindingRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 2, 6, 2)
            rl.setSpacing(8)
            ico, name = _GESTURE_META[g]
            ico_lbl = QLabel(ico)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:14px;")
            rl.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setFixedWidth(50)
            name_lbl.setStyleSheet("font-size:12px;")
            rl.addWidget(name_lbl, 0, Qt.AlignVCenter)
            cb = QComboBox()
            cb.addItem("无", userData=None)
            for a in ACTIONS:
                cb.addItem(_ACTION_LABEL[a], userData=a)
            self._populate_combo(g, cb)
            cb.currentIndexChanged.connect(lambda _idx, gg=g: self._on_binding_changed(gg))
            self._binding_combos[g] = cb
            self._binding_rows[g] = row
            rl.addWidget(cb, 1, Qt.AlignVCenter)
            cl.addWidget(row)

        # ③ 实时试用
        title2 = QLabel("③ 实时试用")
        title2.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;margin-top:6px;")
        cl.addWidget(title2)
        self._trial_now = QLabel("（未启动）")
        self._trial_now.setStyleSheet("color:#ff6e7f;font-size:14px;font-weight:600;")
        cl.addWidget(self._trial_now)
        self._history_lbl = QLabel("（无历史）")
        self._history_lbl.setStyleSheet("color:rgba(255,255,255,170);font-size:11px;font-family:Consolas,monospace;")
        self._history_lbl.setWordWrap(True)
        cl.addWidget(self._history_lbl)

        # 控制按钮
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        b_tutorial = QPushButton("重看教学")
        b_tutorial.setObjectName("SecondaryButton")
        b_tutorial.clicked.connect(self._on_show_tutorial)
        ctrl.addWidget(b_tutorial)
        b_start = QPushButton("启动手势")
        b_start.setObjectName("PrimaryButton")
        b_start.clicked.connect(lambda: self._bridge.start())
        ctrl.addWidget(b_start)
        b_stop = QPushButton("停止")
        b_stop.setObjectName("SecondaryButton")
        b_stop.clicked.connect(lambda: self._bridge.stop())
        ctrl.addWidget(b_stop)
        ctrl.addStretch(1)
        b_default = QPushButton("恢复默认")
        b_default.setObjectName("SecondaryButton")
        b_default.clicked.connect(self._on_reset_defaults)
        ctrl.addWidget(b_default)
        b_export = QPushButton("导出配置")
        b_export.setObjectName("SecondaryButton")
        b_export.clicked.connect(self._on_export)
        ctrl.addWidget(b_export)
        b_import = QPushButton("导入配置")
        b_import.setObjectName("SecondaryButton")
        b_import.clicked.connect(self._on_import)
        ctrl.addWidget(b_import)
        cl.addLayout(ctrl)

        return col

    # ----- 私有：每帧渲染 -----
    @Slot(object)
    def _on_frame_signal(self, snap):
        """主线程槽:engine 每帧推来的 FrameSnapshot。"""
        self._render_snapshot(snap)

    def _poll_latest_snapshot(self):
        """150ms 兜底轮询:防止 Signal 失效时 UI 永远不更新。"""
        snap = self._bridge.latest_snapshot() if hasattr(self._bridge, "latest_snapshot") else None
        if snap is not None:
            self._render_snapshot(snap)

    def _render_snapshot(self, snap):
        """统一的帧渲染入口:Signal 和轮询都走这里。"""
        self._update_preview(snap)
        self._update_status_light(snap)
        self._update_diagnostics(snap)
        self._update_sync_highlight(snap)

    def _update_preview(self, snap):
        if snap is None or snap.frame_rgb is None:
            return
        expected = snap.frame_w * snap.frame_h * 3
        if len(snap.frame_rgb) != expected:
            return
        try:
            # Spec §3 边界 #5:自适应降级。如果 setPixmap 耗时 > 50ms 降到 0.5x,
            # > 100ms 降到 0.25x。状态栏提示用户。
            scale = getattr(self, "_preview_scale", 1.0)
            t0 = time.perf_counter()
            img = QImage(snap.frame_rgb, snap.frame_w, snap.frame_h, QImage.Format_RGB888)
            target_w = max(1, int(self._preview_label.width() * scale))
            target_h = max(1, int(target_w * snap.frame_h / max(snap.frame_w, 1)))
            scaled = img.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview_label.setPixmap(QPixmap.fromImage(scaled))
            dt_ms = (_t.perf_counter() - t0) * 1000
            new_scale = 1.0
            if dt_ms > 100:
                new_scale = 0.25
            elif dt_ms > 50:
                new_scale = 0.5
            if new_scale != scale:
                self._preview_scale = new_scale
                if new_scale < 1.0:
                    self._status_lbl.setText(f"预览降级中:{new_scale}x")
                else:
                    self._status_lbl.setText("预览正常")
        except Exception:
            pass

    def _update_status_light(self, snap):
        from pc_gesture.types import compute_status_light
        threshold = float(self._cfg.sensitivity.get("low_confidence_threshold", 0.6))
        if snap is None:
            color = "#6b7280"
        else:
            light = compute_status_light(snap, low_confidence_threshold=threshold)
            color = {"red": "#ef4444", "yellow": "#eab308", "green": "#22c55e"}.get(light, "#6b7280")
            if self._teaching_check.isChecked():
                color = "#3b82f6"  # 教学:蓝色
        self._status_light.setStyleSheet(
            f"background:{color};border-radius:10px;border:2px solid #1f2937;"
        )

    def _update_diagnostics(self, snap):
        if snap is None or not snap.hands:
            # 没有手:保留最后位置(snap is None)或显示「—」
            if snap is None:
                self._hand_xy_lbl.setText("手位置: —")
                self._conf_lbl.setText("置信度: —")
                self._slot_lbl.setText("Slot: —")
            else:
                # 之前看到了手现在没了:保留「—」
                self._hand_xy_lbl.setText("手位置: —(手离开画面)")
                self._conf_lbl.setText("置信度: —")
                self._slot_lbl.setText("Slot: —")
            # 清手指灯
            for key, (light, st) in self._finger_lights.items():
                if self._finger_state_prev.get(key) is not None:
                    light.setText("○")
                    light.setStyleSheet("color:#6b7280;font-size:14px;")
                    st.setText("卷曲")
                    self._finger_state_prev[key] = None
            return

        # 有手:取置信度最高的一个(单人取 A,双人取置信度高的)
        hand = max(snap.hands, key=lambda h: h.confidence)
        self._hand_xy_lbl.setText(f"手位置: ({hand.wrist_xy[0]:.2f}, {hand.wrist_xy[1]:.2f})")
        self._conf_lbl.setText(f"置信度: {hand.confidence:.2f}")
        self._slot_lbl.setText(f"Slot: {hand.slot}")
        # 置信度颜色
        threshold = float(self._cfg.sensitivity.get("low_confidence_threshold", 0.6))
        conf_color = "#22c55e" if hand.confidence >= threshold else "#f97316"
        self._conf_lbl.setStyleSheet(f"color:{conf_color};font-size:11px;font-weight:600;")
        # 手指灯(只在切换时更新)
        for key, (light, st) in self._finger_lights.items():
            cur = bool(hand.finger_states.get(key, False))
            prev = self._finger_state_prev.get(key)
            if cur != prev:
                if cur:
                    light.setText("●")
                    light.setStyleSheet("color:#22c55e;font-size:14px;")
                    st.setText("伸直")
                else:
                    light.setText("○")
                    light.setStyleSheet("color:#6b7280;font-size:14px;")
                    st.setText("卷曲")
                self._finger_state_prev[key] = cur
        # 手势状态行
        for g, lbl in self._diag_gesture_labels.items():
            if hand.static_gesture == g:
                lbl.setText("✓ 识别中")
                lbl.setStyleSheet("color:#22c55e;font-size:11px;font-weight:600;")
            else:
                lbl.setText("—")
                lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
        self._last_hand_seen_at = time.time()

    def _update_sync_highlight(self, snap):
        if snap is None or not snap.hands:
            return
        # 用 static_gesture 触发高亮(每帧都更新)
        hand = max(snap.hands, key=lambda h: h.confidence)
        if hand.static_gesture == "NONE":
            return
        g = hand.static_gesture
        if g == self._current_gesture:
            return  # 已高亮
        self._current_gesture = g
        # 1. 图卡对应行
        if g in self._cheat_rows:
            self._cheat_rows[g].setStyleSheet(
                "background:rgba(34,197,94,0.4);border-radius:6px;"
            )
            QTimer.singleShot(2000, lambda gg=g: self._cheat_rows[gg].setStyleSheet(""))
        # 2. 映射下拉行
        if g in self._binding_rows:
            self._binding_rows[g].setStyleSheet(
                "background:rgba(34,197,94,0.4);border-radius:6px;"
            )
            QTimer.singleShot(2000, lambda gg=g: self._binding_rows[gg].setStyleSheet(""))
        # 3. 试用当前识别
        self._trial_now.setText(_GESTURE_NAME.get(g, g))
        self._trial_now.setStyleSheet("color:#22c55e;font-size:14px;font-weight:600;")

    # ----- 私有：教程/生命周期 -----
    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(50, self._maybe_show_tutorial)

    def _maybe_show_tutorial(self):
        if self._cfg.tutorial_done:
            return
        eng = self._bridge.engine
        if eng is None:
            return
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()

    def _on_show_tutorial(self):
        from ppt_qt.pages.gesture_tutorial_dialog import GestureTutorialDialog
        dlg = GestureTutorialDialog(bridge=self._bridge, parent=self)
        dlg.exec()

    # ----- 私有：业务逻辑(保持原样) -----
    def _on_teaching_toggled(self, on: bool) -> None:
        self._bridge.set_teaching_mode(bool(on))
        self._status_lbl.setText(
            f"教学模式：{'开（只识别不派发）' if on else '关'}"
        )

    def _populate_combo(self, gesture: str, cb: QComboBox) -> None:
        cur = self._cfg.get_binding(gesture)
        for i in range(cb.count()):
            if cb.itemData(i) == cur:
                cb.setCurrentIndex(i)
                return

    def _on_binding_changed(self, gesture: str) -> None:
        cb = self._binding_combos[gesture]
        action = cb.currentData()
        self._cfg.set_binding(gesture, action)
        self._bridge.save()
        self._refresh_query_hint()
        # Sync the cheat-card row label too.
        if gesture in self._cheat_rows:
            label = _ACTION_LABEL.get(action, "（未绑定）") if action else "（未绑定）"
            self._cheat_rows[gesture].__dict__["_action_lbl"].setText(
                f"→ {label}" if action else "（未绑定）"
            )
        self._status_lbl.setText(f"已更新 {gesture} -> {action or '禁用'}")

    def _refresh_query_hint(self) -> None:
        sel = self._query_combo.currentData()
        if sel is None:
            used = {g for g, a in self._cfg.bindings.items() if a}
            free = [g for g in GESTURES if g not in used]
            self._query_hint.setText("未绑定: " + ", ".join(f"{_GESTURE_NAME[g]}({g})" for g in free) or "（全部已绑定）")
        else:
            bound = [g for g in GESTURES if self._cfg.get_binding(g) == sel]
            if bound:
                self._query_hint.setText("绑定该动作: " + ", ".join(f"{_GESTURE_NAME[g]}({g})" for g in bound))
            else:
                self._query_hint.setText("无手势绑定该动作")

    def _on_reset_defaults(self) -> None:
        self._cfg.reset_bindings()
        self._bridge.save()
        for g, cb in self._binding_combos.items():
            self._populate_combo(g, cb)
        self._refresh_query_hint()
        self._status_lbl.setText("已恢复默认映射")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "gesture_config.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._cfg.raw, f, ensure_ascii=False, indent=2)
            self._status_lbl.setText(f"已导出到 {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"JSON 解析失败: {e}")
            return
        if "bindings" in data and isinstance(data["bindings"], dict):
            self._cfg.import_dict(data["bindings"])
            self._bridge.save()
            for g, cb in self._binding_combos.items():
                self._populate_combo(g, cb)
            self._refresh_query_hint()
            self._status_lbl.setText(f"已导入 {os.path.basename(path)}")
        else:
            QMessageBox.warning(self, "导入失败", "JSON 缺少 bindings 字段")

    def _on_bridge_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def _on_bridge_fps(self, fps: float) -> None:
        prev = self._status_lbl.text()
        if "·" in prev:
            base = prev.split("·")[0].strip()
        else:
            base = prev
        self._status_lbl.setText(f"{base} · FPS {fps:.1f}")

    def _poll_bridge_gestures(self) -> None:
        """Pull new entries from ``bridge.recent_gestures()`` and update the
        trial panel. The bridge's ring buffer is the source of truth; the
        page just consumes it at ~150 ms cadence.
        """
        recent = self._bridge.recent_gestures() if hasattr(self._bridge, "recent_gestures") else []
        # Find any entries newer than what we've already shown.
        new_entries = [r for r in recent if float(r.get("ts") or 0.0) > self._last_seen_ts]
        if not new_entries:
            # Reset "current" indicator if nothing new in a while.
            if self._current_gesture is not None and time.time() - self._last_seen_ts > 2.0:
                self._current_gesture = None
                self._trial_now.setText("（未识别）")
            return
        for entry in new_entries:
            ts = float(entry.get("ts") or 0.0)
            gesture = str(entry.get("gesture") or "")
            action = entry.get("action")
            if not gesture or gesture == self._current_gesture:
                continue
            self._current_gesture = gesture
            self._trial_now.setText(_GESTURE_NAME.get(gesture, gesture))
            self._history.insert(0, {"ts": ts or time.time(), "gesture": gesture, "action": action})
            self._history = self._history[:5]
            self._last_seen_ts = max(self._last_seen_ts, ts or time.time())
            # Highlight the matching row in the cheat card (green flash, 2s).
            if hasattr(self, "_cheat_rows") and gesture in self._cheat_rows:
                self._cheat_rows[gesture].setStyleSheet(
                    "background:rgba(34,197,94,0.4);border-radius:6px;"
                )
                QTimer.singleShot(
                    2000,
                    lambda g=gesture: self._cheat_rows[g].setStyleSheet("")
                )
        lines = []
        for h in self._history:
            t = time.strftime("%H:%M:%S", time.localtime(float(h.get("ts") or 0.0)))
            aname = _ACTION_LABEL.get(h["action"], h["action"] or "无")
            gname = _GESTURE_NAME.get(h["gesture"], h["gesture"])
            lines.append(f"{t} {gname} -> {aname}")
        self._history_lbl.setText("\n".join(lines) or "（无历史）")

    # ----- 公开 API（向后兼容） -----
    def set_status(self, text: str) -> None:
        self._on_bridge_status(text)

    def set_fps(self, fps: float) -> None:
        self._on_bridge_fps(fps)