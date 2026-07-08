"""Gesture control page: 7-slot binding editor / live trial / control buttons."""
from __future__ import annotations

import json
import os
import time
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QFrame,
    QSpinBox, QDoubleSpinBox,
)

from pc_gesture.config import GESTURES, ACTIONS, TIP_GESTURES

# 手势显示:枚举 → emoji + 中文名
_GESTURE_META = {
    "OK":            ("👌", "OK 手势"),
    "L_SIGN":        ("🤙", "L 手势"),
    "THREE_FINGERS": ("🤟", "三指"),
    "POINTING_UP":   ("☝",  "食指"),
    "SCISSORS":      ("✌",  "剪刀手"),
    "FIST":          ("✊", "拳头"),
    "PALM":          ("🖐", "张掌"),
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

# 9-event 提示(emoji + 中文名)
_TIP_GESTURE_META = {
    "L_HAND_INDEX":    ("👆", "左手拇指触食指"),
    "L_HAND_MIDDLE":   ("🖕", "左手拇指触中指"),
    "L_HAND_RING":     ("💍", "左手拇指触无名指"),
    "L_HAND_PINKY":    ("🤙", "左手拇指触小拇指"),
    "R_HAND_INDEX":    ("👆", "右手拇指触食指"),
    "R_HAND_MIDDLE":   ("🖕", "右手拇指触中指"),
    "R_HAND_RING":     ("💍", "右手拇指触无名指"),
    "R_HAND_PINKY":    ("🤙", "右手拇指触小拇指"),
    "HANDS_INTERLOCK": ("🤝", "双手十指相扣"),
}


class GesturePage(QWidget):
    def __init__(self, *, bridge, on_status=None, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = bridge.cfg
        self._on_status = on_status
        self._history: List[Dict] = []
        self._current_gesture: Optional[str] = None
        # ---- 9-event: tip combo boxes(在 _build_right_column 末尾填充) ----
        self._tip_combos: List[QComboBox] = []

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

        # ---- P0.2:互锁进度条 overlay(双手互锁 dwell 时显示) ----
        # 必须先创建 QTimer 再 .start(),所以放在 .start() 前面
        self._interlock_timer = QTimer(self)
        self._interlock_timer.setInterval(100)
        self._interlock_timer.timeout.connect(self._update_interlock_progress)
        self._interlock_timer.start()

        # ---- 9-event: 构造完成后立即应用 operator_mode 状态(单/双人) ----
        self._refresh_tip_combos_enabled()

        # ---- 浮动 toast 反馈(每次手势触发时短暂显示) ----
        # 作为 self 的子 widget 而不是 layout 项,不会影响 column reflow
        self._toast = QLabel(self)
        self._toast.setAlignment(Qt.AlignCenter)
        self._toast.setStyleSheet(
            "background:rgba(34,197,94,0.92);color:#ffffff;"
            "font-size:20px;font-weight:600;padding:14px 28px;"
            "border-radius:12px;"
        )
        self._toast.setVisible(False)
        self._toast.setMinimumWidth(280)
        self._toast.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)

        # ---- P0.2:互锁进度条 overlay(双手互锁 dwell 时显示) ----
        # 比 toast 更宽,带进度条,允许取消
        self._interlock_progress = QLabel(self)
        self._interlock_progress.setAlignment(Qt.AlignCenter)
        self._interlock_progress.setStyleSheet(
            "background:rgba(234,179,8,0.95);color:#1f2937;"
            "font-size:16px;font-weight:600;padding:16px 32px;"
            "border-radius:12px;"
        )
        self._interlock_progress.setVisible(False)
        self._interlock_progress.setMinimumWidth(360)
        self._interlock_progress.setAttribute(Qt.WA_TransparentForMouseEvents)

        # resizeEvent 重定位 toast(浮动在父 widget 中下方)
        self.resizeEvent = self._make_resize_event(self.resizeEvent)

    def _make_resize_event(self, original):
        def _on_resize(event):
            if original is not None:
                original(event)
            self._reposition_toast()
        return _on_resize

    def _reposition_toast(self) -> None:
        if not hasattr(self, "_toast"):
            return
        # 浮动在父 widget 下方居中
        w = self._toast.sizeHint().width()
        h = self._toast.sizeHint().height()
        x = (self.width() - w) // 2
        y = int(self.height() * 0.65)
        self._toast.setGeometry(x, y, w, h)

    def _show_toast(self, text: str, duration_ms: int = 1500) -> None:
        """P0.1:显示大字号 toast 反馈手势触发。"""
        if not hasattr(self, "_toast"):
            return
        self._toast.setText(text)
        self._toast.adjustSize()
        self._reposition_toast()
        self._toast.raise_()
        self._toast.show()
        self._toast_timer.start(duration_ms)

    def _update_interlock_progress(self) -> None:
        """P0.2:每 100ms 轮询 interlock 进度,显示进度条 overlay。

        双手互锁进入 dwell 时显示「🤝 互锁中... 1.2s / 2.0s」,
        用户拆开双手时立即消失(取消)。
        """
        if not hasattr(self, "_interlock_progress"):
            return
        sem = getattr(self._bridge, "_semantics", None)
        if sem is None:
            self._interlock_progress.setVisible(False)
            self._interlock_timer.stop()
            return
        now = time.monotonic()
        progress = sem.interlock_progress(now)
        if progress <= 0.0:
            self._interlock_progress.setVisible(False)
            return
        try:
            dwell = float(self._cfg.sensitivity.get("interlock_min_dwell_s", 2.0))
        except (TypeError, ValueError):
            dwell = 2.0
        elapsed = progress * dwell
        # 简易文本进度条(用 ▏▎▍▌▋▊▉█ 字符)
        bar_len = 16
        filled = int(progress * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        text = f"🤝 互锁中  {elapsed:.1f}s / {dwell:.1f}s  {bar}  拆开取消"
        self._interlock_progress.setText(text)
        self._interlock_progress.adjustSize()
        w = self._interlock_progress.sizeHint().width()
        h = self._interlock_progress.sizeHint().height()
        x = (self.width() - w) // 2
        y = int(self.height() * 0.55)
        self._interlock_progress.setGeometry(x, y, w, h)
        self._interlock_progress.raise_()
        self._interlock_progress.show()

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
        """Build the right column: mapping table + binding + trial + controls."""
        col = QFrame()
        col.setObjectName("GlassCard")
        cl = QVBoxLayout(col)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(8)

        # P1.1:9-event 手势-动作对照表(紧凑,2 列)
        # 比之前 cheat card 信息密度高,只显示 emoji+动作,藏到可折叠区
        table_title = QLabel("📖 手势速查")
        table_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        cl.addWidget(table_title)
        self._mapping_table_toggle = QCheckBox("显示对照表")
        self._mapping_table_toggle.setChecked(True)  # 默认展开
        self._mapping_table_toggle.toggled.connect(self._on_mapping_table_toggle)
        cl.addWidget(self._mapping_table_toggle)
        self._mapping_table = QWidget()
        self._mapping_table_layout = QGridLayout(self._mapping_table)
        self._mapping_table_layout.setContentsMargins(0, 0, 0, 0)
        self._mapping_table_layout.setSpacing(4)
        cl.addWidget(self._mapping_table)
        self._populate_mapping_table()

        # ① 手势映射(去掉原 cheat card,节省页面空间)
        title1 = QLabel("① 手势映射")
        title1.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
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

        # ---- 9-event: 9 个新 combo box(仅 dual 模式有效) ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color:rgba(255,255,255,80);margin:8px 0;")
        cl.addWidget(sep)
        tip_label = QLabel("新 9-事件(需双人模式)")
        tip_label.setStyleSheet("color:rgba(255,255,255,200);font-size:12px;font-weight:600;margin-top:4px;")
        cl.addWidget(tip_label)
        for g in TIP_GESTURES:
            row = QFrame()
            row.setObjectName("TipBindingRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 2, 6, 2)
            rl.setSpacing(8)
            emoji, name = _TIP_GESTURE_META.get(g, ("", g))
            ico_lbl = QLabel(emoji)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:14px;")
            rl.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            name_lbl = QLabel(name)
            name_lbl.setMinimumWidth(180)
            name_lbl.setStyleSheet("font-size:12px;")
            rl.addWidget(name_lbl, 0, Qt.AlignVCenter)
            cb = QComboBox()
            cb.addItem("无", userData=None)
            for a in ACTIONS:
                cb.addItem(_ACTION_LABEL[a], userData=a)
            # set current from cfg.tip_bindings
            cur = self._cfg.get_tip_binding(g)
            for i in range(cb.count()):
                if cb.itemData(i) == cur:
                    cb.setCurrentIndex(i)
                    break
            cb.currentIndexChanged.connect(
                lambda v, gg=g: self._on_tip_binding_changed(gg, v)
            )
            self._tip_combos.append(cb)
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
        # 7 旧 gesture 删除后,tutorial_dialog 已删,"重看教学"按钮移除
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

        # ----- ④ 灵敏度调节(可折叠,默认折叠) -----
        # 之前抽到 cfg.sensitivity 的 9 个 magic number 没有 UI 可调,用户只能改 JSON。
        # 现在每个字段一个 QDoubleSpinBox + 重置默认按钮。
        sens_card = QFrame()
        sens_card.setObjectName("GlassCard")
        sens_l = QVBoxLayout(sens_card)
        sens_l.setContentsMargins(12, 12, 12, 12)
        sens_l.setSpacing(6)
        sens_title = QLabel("④ 灵敏度调节(高级)")
        sens_title.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        sens_l.addWidget(sens_title)
        # 可折叠 — 用一个 QCheckBox 当 toggle,取消勾选时隐藏内部
        self._sens_expand = QCheckBox("显示灵敏度调节")
        self._sens_expand.setChecked(False)
        self._sens_expand.toggled.connect(self._on_sens_expand_toggled)
        sens_l.addWidget(self._sens_expand)
        # 内部 panel(默认隐藏)
        self._sens_panel = QWidget()
        self._sens_panel.setVisible(False)
        sens_inner = QVBoxLayout(self._sens_panel)
        sens_inner.setContentsMargins(0, 0, 0, 0)
        sens_inner.setSpacing(4)
        # 16 个字段:label + spinbox
        # (label, key, default, min, max, step, scale, suffix)
        sens_fields = [
            ("拇-食指尖接触比例",  "thumb_touch_ratio",  0.08, 0.0, 1.0, 0.01, 3, ""),
            ("拇-食指伸直比例",    "thumb_extend_ratio", 0.18, 0.0, 1.0, 0.01, 3, ""),
            ("伸直 Y 偏移(严)",    "ext_strict_y",       0.025, 0.0, 0.1, 0.005, 3, ""),
            ("伸直 Y 偏移(松)",    "ext_relaxed_y",      0.015, 0.0, 0.1, 0.005, 3, ""),
            ("卷曲 Y 偏移",        "curl_y",             0.005, 0.0, 0.05, 0.001, 3, ""),
            ("Y 模糊容差(2D 兜底)", "ambiguous_y_tolerance", 0.005, 0.0, 0.05, 0.001, 3, ""),
            ("2D 距离阈值",         "ext_2d_ratio",       0.85, 0.0, 1.5, 0.01, 2, ""),
            ("L 拇指伸出阈值",     "l_sign_thumb_extend_ratio", 0.30, 0.0, 1.0, 0.01, 2, ""),
            ("冷却时间 (ms)",      "gesture_cooldown_ms", 400, 0, 3000, 50, 0, "ms"),
            ("手势重置空闲 (s)",   "static_reset_idle_s", 0.3, 0.0, 2.0, 0.05, 2, "s"),
            ("手部消失清理 (s)",   "hand_lost_cleanup_s", 0.5, 0.0, 3.0, 0.1, 1, "s"),
            ("置信度阈值",         "low_confidence_threshold", 0.6, 0.0, 1.0, 0.05, 2, ""),
            ("配对 pointing (s)",  "pairing_pointing_up_s", 1.0, 0.0, 5.0, 0.1, 1, "s"),
            ("配对窗口 (ms)",      "pairing_window_ms",  3000, 500, 10000, 100, 0, "ms"),
            ("激光平滑",           "laser_smoothing",    0.55, 0.0, 0.95, 0.05, 2, ""),
        ]
        self._sens_spins = {}  # key → QSpinBox / QDoubleSpinBox
        from pc_gesture.config import DEFAULT_GESTURE_CONFIG
        default_sens = DEFAULT_GESTURE_CONFIG["sensitivity"]
        for label, key, default, mn, mx, step, decimals, suffix in sens_fields:
            row = QHBoxLayout()
            row.setSpacing(6)
            lbl = QLabel(label)
            lbl.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
            lbl.setMinimumWidth(160)
            row.addWidget(lbl)
            current = float(default_sens.get(key, default))
            if decimals == 0:
                spin = QSpinBox()
                spin.setRange(int(mn), int(mx))
                spin.setSingleStep(int(step))
                spin.setValue(int(current))
            else:
                spin = QDoubleSpinBox()
                spin.setRange(mn, mx)
                spin.setSingleStep(step)
                spin.setDecimals(decimals)
                spin.setValue(current)
            spin.setSuffix(f" {suffix}" if suffix else "")
            # error.txt [33]:QTimer debounce 500ms,避免拖动时 ~30 次同步写盘
            spin.valueChanged.connect(
                lambda v, k=key, s=spin: self._debounced_sens_change(k, v, s)
            )
            self._sens_spins[key] = spin
            row.addWidget(spin, 1)
            sens_inner.addLayout(row)
        # 复选框:debug_log(用 self._cfg.sensitivity 读用户当前值,不用 default)
        self._debug_log_check = QCheckBox("调试日志(终端打 [bridge]/[semantics] 日志)")
        self._debug_log_check.setChecked(bool(self._cfg.sensitivity.get("debug_log", False)))
        self._debug_log_check.toggled.connect(self._on_debug_log_toggled)
        sens_inner.addWidget(self._debug_log_check)
        # 重置默认按钮
        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        b_reset = QPushButton("重置默认")
        b_reset.setObjectName("SecondaryButton")
        b_reset.clicked.connect(self._on_sens_reset)
        reset_row.addWidget(b_reset)
        sens_inner.addLayout(reset_row)
        sens_l.addWidget(self._sens_panel)
        cl.addWidget(sens_card)

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
        """统一的帧渲染入口:Signal 和轮询都走这里。

        kasi.txt [42]:之前 4 个子函数每帧都跑(30fps × 4 = 120 调用/秒)。
        改为只在上次 timestamp_ms 不同时才跑;空帧(snap is None)只跑 diagnostics。
        """
        ts = snap.timestamp_ms if snap is not None else None
        if ts == getattr(self, "_last_render_ts", None) and snap is not None:
            # 同一帧(重复推)跳过;但 None 帧每次都跑让 UI 知道"无数据"
            return
        self._last_render_ts = ts
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
            # error.txt [17]:QImage 不复制 buffer,引擎线程下一帧覆写时预览花屏。
            # bytes() 复制一份内存,确保 QImage 不引用引擎的 buffer。
            img = QImage(
                bytes(snap.frame_rgb), snap.frame_w, snap.frame_h, QImage.Format_RGB888
            )
            target_w = max(1, int(self._preview_label.width() * scale))
            target_h = max(1, int(target_w * snap.frame_h / max(snap.frame_w, 1)))
            scaled = img.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._preview_label.setPixmap(QPixmap.fromImage(scaled))
            dt_ms = (time.perf_counter() - t0) * 1000
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
        # kasi.txt [41]:每帧 setStyleSheet 触发 stylesheet 重新计算,
        # 即使 color 没变也跑。加 prev_color 缓存,变了才 setStyleSheet。
        new_ss = f"background:{color};border-radius:10px;border:2px solid #1f2937;"
        if getattr(self, "_status_light_prev_ss", None) != new_ss:
            self._status_light.setStyleSheet(new_ss)
            self._status_light_prev_ss = new_ss

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
        # kasi.txt [12]:之前每帧循环 7 个 label 都 setText + setStyleSheet,
        # 即使 static_gesture 没变也全部重置。30fps × 7 × 2 = 420 次 UI 操作/秒。
        # 改为只在变化时更新(用 prev 缓存当前 active label)。
        active_g = hand.static_gesture
        prev_active = getattr(self, "_diag_active_gesture", None)
        if active_g != prev_active:
            # 把旧 label 重置
            if prev_active and prev_active in self._diag_gesture_labels:
                old_lbl = self._diag_gesture_labels[prev_active]
                old_lbl.setText("—")
                old_lbl.setStyleSheet("color:rgba(255,255,255,140);font-size:11px;")
            # 把新 label 高亮
            if active_g in self._diag_gesture_labels:
                new_lbl = self._diag_gesture_labels[active_g]
                new_lbl.setText("✓ 识别中")
                new_lbl.setStyleSheet("color:#22c55e;font-size:11px;font-weight:600;")
            self._diag_active_gesture = active_g
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
        # error.txt [19]:race condition。第二次触发会覆盖第一次的清除时刻,
        # 导致高亮闪一下就灭。保存 timer 实例,新一次高亮前先 stop 旧 timer。
        # kasi.txt [35]:之前每帧新 QTimer,改用持久 timer(每个 row 一个)复用,
        # 避免 timer 累积。
        for row_dict in (self._binding_rows,):
            if g in row_dict:
                row = row_dict[g]
                # 复用已有的清除 timer(没有就建一个)
                timer = getattr(row, "_clear_timer", None)
                if timer is None:
                    timer = QTimer(self)  # parent=self 防止 GC
                    timer.setSingleShot(2000)
                    timer.timeout.connect(lambda r=row: r.setStyleSheet(""))
                    row._clear_timer = timer
                timer.stop()  # 先停,再 start 等同于 reset
                row.setStyleSheet("background:rgba(34,197,94,0.4);border-radius:6px;")
                timer.start()
        # 3. 试用当前识别
        self._trial_now.setText(_GESTURE_NAME.get(g, g))
        self._trial_now.setStyleSheet("color:#22c55e;font-size:14px;font-weight:600;")

    # ----- 私有：生命周期 -----
    # 7 旧 gesture 删除后,tutorial_dialog 已删(9 事件无对应 7 步教学)。
    # showEvent 保留给未来扩展。

    # ----- 私有：业务逻辑(保持原样) -----
    def _on_teaching_toggled(self, on: bool) -> None:
        self._bridge.set_teaching_mode(bool(on))
        self._status_lbl.setText(
            f"教学模式：{'开（只识别不派发）' if on else '关'}"
        )

    # ----- 灵敏度 UI 回调 -----
    def _on_sens_expand_toggled(self, on: bool) -> None:
        self._sens_panel.setVisible(on)

    def _on_mapping_table_toggle(self, on: bool) -> None:
        self._mapping_table.setVisible(on)

    def _populate_mapping_table(self) -> None:
        """P1.1:填充 9-event 手势-动作对照表。

        2 列布局:左 emoji + 中文名,右当前动作。
        互锁手势单独一行,用黄色突出(danger zone)。
        """
        from pc_gesture.config import DEFAULT_TIP_BINDINGS, ACTIONS
        # emoji + 中文名(hardcoded,稳定)
        desc_map = {
            "L_HAND_INDEX":     "👆 左手拇指触食指",
            "L_HAND_MIDDLE":    "☝ 左手拇指触中指",
            "L_HAND_RING":      "💍 左手拇指触无名指",
            "L_HAND_PINKY":     "🤙 左手拇指触小拇指",
            "R_HAND_INDEX":     "👆 右手拇指触食指",
            "R_HAND_MIDDLE":    "🖕 右手拇指触中指",
            "R_HAND_RING":      "💍 右手拇指触无名指",
            "R_HAND_PINKY":     "🤙 右手拇指触小拇指",
            "HANDS_INTERLOCK":  "🤝 双手十指相扣(2s dwell)",
        }
        action_labels = {
            "NEXT_PAGE":     "下一页",
            "PREV_PAGE":     "上一页",
            "FULL_SCREEN":   "从头放映",
            "FROM_CURRENT":  "从当前放映",
            "BLACK_SCREEN":  "黑屏",
            "WHITE_SCREEN":  "白屏",
            "EXIT":          "退出放映",
            "SCREENSHOT":    "截屏",
            "OPEN_PPT":      "打开PPT",
            "PC_WINDOW_MINIMIZE": "PC最小化",
            "PC_WINDOW_RESTORE":  "PC恢复",
        }
        gestures = [
            "L_HAND_INDEX", "L_HAND_MIDDLE", "L_HAND_RING", "L_HAND_PINKY",
            "R_HAND_INDEX", "R_HAND_MIDDLE", "R_HAND_RING", "R_HAND_PINKY",
            "HANDS_INTERLOCK",
        ]
        # 2 列 grid
        for idx, g in enumerate(gestures):
            is_danger = (g == "HANDS_INTERLOCK")
            lbl = QLabel(desc_map.get(g, g))
            lbl.setStyleSheet(
                "color:%s;font-size:11px;" % ("#fde68a" if is_danger else "rgba(255,255,255,200)")
            )
            # 优先从 cfg.tip_bindings 读,否则用默认
            if hasattr(self._cfg, "tip_bindings") and self._cfg.tip_bindings:
                action = self._cfg.tip_bindings.get(g) or DEFAULT_TIP_BINDINGS.get(g)
            else:
                action = DEFAULT_TIP_BINDINGS.get(g)
            action_lbl = QLabel(action_labels.get(action, "—") if action else "—")
            action_lbl.setStyleSheet(
                "color:%s;font-size:11px;font-weight:600;"
                % ("#fbbf24" if is_danger else "#86efac")
            )
            row = idx // 2
            col_pair = idx % 2
            self._mapping_table_layout.addWidget(lbl, row, col_pair * 2)
            self._mapping_table_layout.addWidget(action_lbl, row, col_pair * 2 + 1)

    def _on_sens_changed(self, key: str, value) -> None:
        """spinbox 变化时把值写回 cfg,持久化到磁盘。"""
        if "sensitivity" not in self._cfg.raw or not isinstance(self._cfg.raw["sensitivity"], dict):
            self._cfg.raw["sensitivity"] = {}
        self._cfg.raw["sensitivity"][key] = value
        self._bridge.save()

    def _debounced_sens_change(self, key: str, value, spin) -> None:
        """error.txt [33]:QTimer debounce 500ms 合并连续 spinbox 变化。

        拖动 spinbox 时每次 valueChanged 都同步写盘会卡主线程
        (~30 次/秒),用单 timer 防抖后只在最后一次写一次。
        """
        timer = getattr(self, "_sens_debounce_timers", None)
        if timer is None:
            self._sens_debounce_timers = {}
        # 取消旧 timer
        old = self._sens_debounce_timers.get(key)
        if old is not None:
            old.stop()
        # 启动新 timer(记下 callback 以便 flush)
        t = QTimer(self)
        t.setSingleShot(True)
        t.setInterval(500)
        t._pending = (key, value)  # 记下要写的内容
        t.timeout.connect(lambda: self._on_sens_changed(key, value))
        t.start()
        self._sens_debounce_timers[key] = t

    def _flush_sens_debounce(self) -> None:
        """测试用:立即同步所有未触发的 spinbox 防抖写盘。"""
        timers = getattr(self, "_sens_debounce_timers", {})
        for t in list(timers.values()):
            t.stop()
            # 主动调用 callback
            key, value = t._pending
            self._on_sens_changed(key, value)
        self._sens_debounce_timers = {}

    def _on_debug_log_toggled(self, on: bool) -> None:
        if "sensitivity" not in self._cfg.raw or not isinstance(self._cfg.raw["sensitivity"], dict):
            self._cfg.raw["sensitivity"] = {}
        self._cfg.raw["sensitivity"]["debug_log"] = bool(on)
        self._bridge.save()

    def _on_sens_reset(self) -> None:
        """重置所有灵敏度为默认值(保留 debug_log 现状)。"""
        from pc_gesture.config import DEFAULT_GESTURE_CONFIG
        defaults = dict(DEFAULT_GESTURE_CONFIG["sensitivity"])
        debug_log = self._cfg.raw.get("sensitivity", {}).get("debug_log", False)
        self._cfg.raw["sensitivity"] = defaults
        self._cfg.raw["sensitivity"]["debug_log"] = debug_log
        for key, spin in self._sens_spins.items():
            value = defaults.get(key, 0.0)
            if isinstance(spin, QSpinBox):
                spin.setValue(int(value))
            else:
                spin.setValue(float(value))
        self._debug_log_check.setChecked(debug_log)
        self._bridge.save()
        self._status_lbl.setText("灵敏度已重置为默认")

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
        self._status_lbl.setText(f"已更新 {gesture} -> {action or '禁用'}")

    def _on_tip_binding_changed(self, gesture: str, idx: int) -> None:
        """9-event combo box 变化时写回 cfg,持久化。"""
        cb = self.sender()
        if cb is None:
            return
        action = cb.itemData(idx)
        try:
            self._cfg.set_tip_binding(gesture, action)
        except ValueError:
            return
        self._bridge.save()
        self._status_lbl.setText(f"已更新 {gesture} -> {action or '禁用'}")

    def _refresh_tip_combos_enabled(self) -> None:
        """9 个 tip combo 总 enable(7 旧 gesture 删除后,9 事件支持单/双人模式)。"""
        for cb in self._tip_combos:
            cb.setEnabled(True)
            cb.setToolTip("")

    def _refresh_query_hint(self) -> None:
        sel = self._query_combo.currentData()
        if sel is None:
            used = {g for g, a in self._cfg.tip_bindings.items() if a}
            free = [g for g in TIP_GESTURES if g not in used]
            self._query_hint.setText("未绑定: " + ", ".join(f"{_TIP_GESTURE_META.get(g, ('', g))[1]}({g})" for g in free) or "（全部已绑定）")
        else:
            bound = [g for g in TIP_GESTURES if self._cfg.get_tip_binding(g) == sel]
            if bound:
                self._query_hint.setText("绑定该动作: " + ", ".join(f"{_GESTURE_NAME[g]}({g})" for g in bound))
            else:
                self._query_hint.setText("无手势绑定该动作")

    def _on_reset_defaults(self) -> None:
        self._cfg.reset_bindings()
        # 9-event: 重置 tip_bindings 到默认值
        from pc_gesture.config import DEFAULT_TIP_BINDINGS
        for g in TIP_GESTURES:
            self._cfg.set_tip_binding(g, DEFAULT_TIP_BINDINGS.get(g))
        self._bridge.save()
        for g, cb in self._binding_combos.items():
            self._populate_combo(g, cb)
        # 9-event: 同步刷新 9 个 tip combo 当前值
        for g, cb in zip(TIP_GESTURES, self._tip_combos):
            cur = self._cfg.get_tip_binding(g)
            for i in range(cb.count()):
                if cb.itemData(i) == cur:
                    cb.setCurrentIndex(i)
                    break
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
            # 高亮映射行(green flash, 2s) — cheat card 已移除,只高亮 binding row
            if hasattr(self, "_binding_rows") and gesture in self._binding_rows:
                self._binding_rows[gesture].setStyleSheet(
                    "background:rgba(34,197,94,0.4);border-radius:6px;"
                )
                QTimer.singleShot(
                    2000,
                    lambda g=gesture: self._binding_rows[g].setStyleSheet("")
                )
            # P0.1:大字号 toast 反馈(显示动作名)
            action_name = _ACTION_LABEL.get(action, "") if action else ""
            emoji, name = _GESTURE_META.get(gesture, ("", gesture))
            if action_name:
                toast_text = f"{emoji}  {name}  →  {action_name}"
            else:
                toast_text = f"{emoji}  {name}"
            self._show_toast(toast_text, duration_ms=1500)
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