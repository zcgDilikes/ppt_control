"""Tests for the sensitivity editor UI in GesturePage.

验证 16 个灵敏度 spinbox 控件 + debug_log checkbox + 重置默认按钮
能正确读写 cfg.sensitivity 并通过 bridge.save() 持久化。
"""

import json
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# Headless Qt for tests
from PySide6.QtWidgets import QApplication, QSpinBox, QDoubleSpinBox, QCheckBox, QWidget

# Make sure QApplication exists
_app = QApplication.instance() or QApplication([])


def _make_bridge():
    """Mock GestureBridge with cfg + save + minimal attribute stubs."""
    from unittest.mock import MagicMock
    from pc_gesture.config import load_gesture_config, save_gesture_config
    cfg = load_gesture_config()
    bridge = MagicMock()
    bridge.cfg = cfg
    bridge.save_count = 0

    def fake_save():
        bridge.save_count += 1
        save_gesture_config(bridge.cfg)

    bridge.save.side_effect = fake_save
    return bridge


def _make_page(bridge=None):
    from ppt_qt.pages.gesture_page import GesturePage
    if bridge is None:
        bridge = _make_bridge()
    page = GesturePage(bridge=bridge)
    return page, bridge


def test_sens_panel_initially_hidden():
    """灵敏度面板默认隐藏,要勾选 checkbox 才显示。"""
    page, _ = _make_page()
    assert page._sens_panel.isVisibleTo(page) is False
    assert page._sens_expand.isChecked() is False


def test_sens_expand_toggle_shows_panel():
    page, _ = _make_page()
    page._sens_expand.setChecked(True)
    # isVisibleTo(page) 检查相对父 widget 的可见性,不受 top-level window 状态影响
    assert page._sens_panel.isVisibleTo(page) is True
    page._sens_expand.setChecked(False)
    assert page._sens_panel.isVisibleTo(page) is False


def test_all_15_spinboxes_exist():
    """验证 15 个数值字段都有 spinbox,默认值正确。"""
    page, bridge = _make_page()
    expected_keys = [
        "thumb_touch_ratio", "thumb_extend_ratio",
        "ext_strict_y", "ext_relaxed_y", "curl_y",
        "ambiguous_y_tolerance", "ext_2d_ratio",
        "l_sign_thumb_extend_ratio",
        "gesture_cooldown_ms",
        "static_reset_idle_s", "hand_lost_cleanup_s",
        "low_confidence_threshold",
        "pairing_pointing_up_s", "pairing_window_ms",
        "laser_smoothing",
    ]
    assert len(page._sens_spins) == 15
    for key in expected_keys:
        assert key in page._sens_spins, f"missing spinbox for {key}"


def test_spinbox_initial_values_match_defaults():
    page, bridge = _make_page()
    expected = {
        "thumb_touch_ratio": 0.08,
        "thumb_extend_ratio": 0.18,
        "ext_strict_y": 0.025,
        "ext_relaxed_y": 0.015,
        "curl_y": 0.005,
        "ambiguous_y_tolerance": 0.005,
        "ext_2d_ratio": 0.85,
        "l_sign_thumb_extend_ratio": 0.30,
        "gesture_cooldown_ms": 400,
        "static_reset_idle_s": 0.3,
        "hand_lost_cleanup_s": 0.5,
        "low_confidence_threshold": 0.6,
        "pairing_pointing_up_s": 1.0,
        "pairing_window_ms": 3000,
        "laser_smoothing": 0.55,
    }
    for key, val in expected.items():
        spin = page._sens_spins[key]
        if isinstance(spin, QSpinBox):
            assert spin.value() == val, f"{key}: spinbox {spin.value()} != {val}"
        else:
            assert abs(spin.value() - val) < 1e-9, f"{key}: spinbox {spin.value()} != {val}"


def test_change_spinbox_writes_to_cfg_and_saves():
    """调 spinbox → cfg 更新 → bridge.save() 调一次。"""
    page, bridge = _make_page()
    bridge.save_count = 0
    spin = page._sens_spins["gesture_cooldown_ms"]
    spin.setValue(750)
    # [33] debounce 500ms,测试时立即 flush
    page._flush_sens_debounce()
    assert bridge.cfg.sensitivity["gesture_cooldown_ms"] == 750
    assert bridge.save_count == 1


def test_change_float_spinbox_writes_to_cfg():
    page, bridge = _make_page()
    spin = page._sens_spins["ext_strict_y"]
    spin.setValue(0.04)
    # [33] debounce 500ms,测试时立即 flush
    page._flush_sens_debounce()
    assert abs(bridge.cfg.sensitivity["ext_strict_y"] - 0.04) < 1e-9


def test_debug_log_checkbox_writes_to_cfg():
    """先 setChecked(False) 强制触发信号(避免与初始状态相同时无信号),再 True。"""
    page, bridge = _make_page()
    bridge.save_count = 0
    # 先切到 False(无论初始是什么)
    page._debug_log_check.setChecked(False)
    # 再切到 True,触发 toggled(True)
    page._debug_log_check.setChecked(True)
    assert bridge.cfg.sensitivity["debug_log"] is True
    assert bridge.save_count >= 1


def test_reset_button_restores_defaults_but_keeps_debug_log():
    """重置默认:所有值恢复,但 debug_log 保持当前(用户偏好)。"""
    page, bridge = _make_page()
    # 用户先调了几个值
    page._sens_spins["gesture_cooldown_ms"].setValue(1000)
    page._sens_spins["ext_strict_y"].setValue(0.05)
    page._debug_log_check.setChecked(True)
    # 调 reset
    page._on_sens_reset()
    assert bridge.cfg.sensitivity["gesture_cooldown_ms"] == 400
    assert abs(bridge.cfg.sensitivity["ext_strict_y"] - 0.025) < 1e-9
    assert bridge.cfg.sensitivity["debug_log"] is True  # 保留
    # spinbox 同步
    assert page._sens_spins["gesture_cooldown_ms"].value() == 400
    assert page._debug_log_check.isChecked() is True


def test_reset_button_when_debug_log_was_false_keeps_false():
    page, bridge = _make_page()
    page._debug_log_check.setChecked(False)
    page._on_sens_reset()
    assert bridge.cfg.sensitivity["debug_log"] is False


def test_spinbox_change_does_not_throw_with_invalid_value():
    """spinbox 范围外的值会被 Qt 自动 clamp,不应崩。"""
    page, bridge = _make_page()
    spin = page._sens_spins["gesture_cooldown_ms"]
    spin.setValue(-100)  # clamp to 0
    spin.setValue(999999)  # clamp to 3000
    # 仍然写入 cfg(可能 clamped)
    val = bridge.cfg.sensitivity["gesture_cooldown_ms"]
    assert 0 <= val <= 3000


def test_persistence_across_page_reload(tmp_path):
    """spinbox 调的值通过 bridge.save() 持久化,重新加载后能读回。"""
    # 重新构建 cfg 走磁盘
    cfg_path = tmp_path / "test_cfg.json"
    from pc_gesture.config import load_gesture_config, save_gesture_config, DEFAULT_GESTURE_CONFIG
    cfg = load_gesture_config(path=str(cfg_path))
    save_gesture_config(cfg, str(cfg_path))

    from unittest.mock import MagicMock
    cfg_disk = load_gesture_config(path=str(cfg_path))
    bridge = MagicMock()
    bridge.cfg = cfg_disk
    bridge.save_count = 0

    def fake_save():
        from pc_gesture.config import save_gesture_config
        save_gesture_config(bridge.cfg, str(cfg_path))
        bridge.save_count += 1

    bridge.save.side_effect = fake_save

    from ppt_qt.pages.gesture_page import GesturePage
    page = GesturePage(bridge=bridge)
    # 改 spinbox
    page._sens_spins["gesture_cooldown_ms"].setValue(1234)
    # [33] debounce 500ms,测试时立即 flush
    page._flush_sens_debounce()
    # 验证磁盘
    cfg2 = load_gesture_config(path=str(cfg_path))
    assert cfg2.sensitivity["gesture_cooldown_ms"] == 1234