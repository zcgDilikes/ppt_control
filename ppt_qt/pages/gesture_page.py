"""Gesture control page: 7-slot binding editor / live trial / control buttons."""
from __future__ import annotations

import json
import os
import time
from typing import Optional, List, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QFileDialog, QMessageBox, QSizePolicy, QFrame,
)

from pc_gesture.config import GESTURES, ACTIONS, DEFAULT_BINDINGS

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

# 反向：label -> action name
_LABEL_TO_ACTION = {v: k for k, v in _ACTION_LABEL.items()}

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

        # ---- 反查行 ----
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("查找:"))
        self._query_combo = QComboBox()
        self._query_combo.addItem("（全部未绑定）", userData=None)
        for a in ACTIONS:
            self._query_combo.addItem(_ACTION_LABEL[a], userData=a)
        self._query_combo.currentIndexChanged.connect(self._refresh_query_hint)
        top.addWidget(self._query_combo, 1)
        self._query_hint = QLabel("")
        self._query_hint.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        top.addWidget(self._query_hint, 2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        outer.addLayout(top)

        # ---- 段 1 7 行映射 ----
        map_card = QFrame()
        map_card.setObjectName("GlassCard")
        ml = QVBoxLayout(map_card)
        ml.setContentsMargins(12, 12, 12, 12)
        ml.setSpacing(6)
        title1 = QLabel("① 手势映射")
        title1.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        ml.addWidget(title1)
        self._binding_combos: Dict[str, QComboBox] = {}
        for g in GESTURES:
            row = QHBoxLayout()
            row.setSpacing(8)
            ico, name = _GESTURE_META[g]
            ico_lbl = QLabel(ico)
            ico_lbl.setFixedWidth(24)
            ico_lbl.setStyleSheet("font-size:16px;")
            row.addWidget(ico_lbl, 0, Qt.AlignVCenter)
            row.addWidget(QLabel(name), 0, Qt.AlignVCenter)
            row.addStretch(1)
            cb = QComboBox()
            cb.addItem("无", userData=None)
            for a in ACTIONS:
                cb.addItem(_ACTION_LABEL[a], userData=a)
            cb.setCurrentIndex(0)
            self._populate_combo(g, cb)
            cb.currentIndexChanged.connect(lambda _idx, gg=g: self._on_binding_changed(gg))
            self._binding_combos[g] = cb
            row.addWidget(cb, 0, Qt.AlignVCenter)
            ml.addLayout(row)
        outer.addWidget(map_card)

        # ---- 段 2 试用面板 ----
        trial_card = QFrame()
        trial_card.setObjectName("GlassCard")
        tl = QVBoxLayout(trial_card)
        tl.setContentsMargins(12, 12, 12, 12)
        tl.setSpacing(6)
        title2 = QLabel("② 实时试用")
        title2.setStyleSheet("color:#ffffff;font-size:13px;font-weight:600;")
        tl.addWidget(title2)
        now = QHBoxLayout()
        now.setSpacing(12)
        self._trial_now = QLabel("（未启动）")
        self._trial_now.setStyleSheet("color:#ff6e7f;font-size:14px;font-weight:600;")
        now.addWidget(self._trial_now, 0, Qt.AlignVCenter)
        self._trial_check = QCheckBox("试用模式")
        self._trial_check.setChecked(False)
        self._trial_check.toggled.connect(self._on_trial_toggled)
        now.addWidget(self._trial_check, 0, Qt.AlignVCenter)
        self._preview_check = QCheckBox("显示预览")
        self._preview_check.setChecked(bool(self._cfg.raw.get("show_preview_window", True)))
        self._preview_check.toggled.connect(self._on_preview_toggled)
        now.addWidget(self._preview_check, 0, Qt.AlignVCenter)
        now.addStretch(1)
        tl.addLayout(now)
        # 历史
        self._history_lbl = QLabel("（无历史）")
        self._history_lbl.setStyleSheet("color:rgba(255,255,255,170);font-size:11px;font-family:Consolas,monospace;")
        self._history_lbl.setWordWrap(True)
        tl.addWidget(self._history_lbl)
        outer.addWidget(trial_card)

        # ---- 段 3 控制 ----
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        b_start = QPushButton("启动手势")
        b_start.setObjectName("PrimaryButton")
        b_start.clicked.connect(lambda: bridge.start())
        ctrl.addWidget(b_start)
        b_stop = QPushButton("停止")
        b_stop.setObjectName("SecondaryButton")
        b_stop.clicked.connect(lambda: bridge.stop())
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
        outer.addLayout(ctrl)

        # 状态行
        self._status_lbl = QLabel("未启动")
        self._status_lbl.setStyleSheet("color:rgba(255,255,255,180);font-size:11px;")
        outer.addWidget(self._status_lbl)

        # 初次刷新反查提示
        self._refresh_query_hint()

        # 接 engine 回调
        if bridge.engine is not None:
            bridge.engine._on_status = lambda t: self._on_bridge_status(t)
            bridge.engine._on_fps = lambda f: self._on_bridge_fps(f)
        # 录制识别（写一个内部轮询：从 bridge 的 _history 或 engine._last_gesture 取）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(150)
        self._poll_timer.timeout.connect(self._poll_engine_state)
        self._poll_timer.start()

    # ----- 私有 -----
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

    def _on_trial_toggled(self, on: bool) -> None:
        self._bridge._trial_mode = bool(on)

    def _on_preview_toggled(self, on: bool) -> None:
        self._cfg.raw["show_preview_window"] = bool(on)
        self._bridge.save()
        eng = self._bridge.engine
        if eng is not None and hasattr(eng, "_show_preview"):
            eng._show_preview = bool(on)

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

    def _poll_engine_state(self) -> None:
        eng = self._bridge.engine
        if eng is None:
            return
        last = getattr(eng, "_last_gesture", None)
        if last and last != self._current_gesture:
            self._current_gesture = last
            self._trial_now.setText(_GESTURE_NAME.get(last, last))
            action = self._cfg.get_binding(last)
            self._history.insert(0, {"ts": time.time(), "gesture": last, "action": action})
            self._history = self._history[:5]
            lines = []
            for h in self._history:
                t = time.strftime("%H:%M:%S", time.localtime(h["ts"]))
                aname = _ACTION_LABEL.get(h["action"], h["action"] or "无")
                gname = _GESTURE_NAME.get(h["gesture"], h["gesture"])
                lines.append(f"{t} {gname} -> {aname}")
            self._history_lbl.setText("\n".join(lines) or "（无历史）")
        elif last is None and self._current_gesture is not None:
            self._current_gesture = None
            self._trial_now.setText("（未识别）")

    # ----- 公开 API（向后兼容） -----
    def set_status(self, text: str) -> None:
        self._on_bridge_status(text)

    def set_fps(self, fps: float) -> None:
        self._on_bridge_fps(fps)

    def set_trial_history(self, events: List[Dict]) -> None:
        pass
