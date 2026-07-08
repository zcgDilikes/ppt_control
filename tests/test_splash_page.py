"""Tests for SplashPage (plan §2.3)."""

import pytest

# Headless Qt for tests
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])


def _make_splash():
    from ppt_qt.pages.splash_page import SplashPage
    return SplashPage()


def test_splash_starts_at_0_percent():
    """A freshly-constructed splash must show 0% progress and the
    first-stage status text."""
    splash = _make_splash()
    assert splash.percent == 0
    assert splash.status_text == "加载核心库…"


def test_splash_updates_through_stages():
    """Walking through all 4 stages (importing → loading_model →
    init_camera → ready) drives the progress 0→25→50→75→100 and the
    status text matches each stage."""
    from ppt_qt.pages.splash_page import (
        STAGE_IMPORTING, STAGE_LOADING_MODEL,
        STAGE_INIT_CAMERA, STAGE_READY,
    )
    splash = _make_splash()
    splash.update_progress(STAGE_IMPORTING)
    assert splash.percent == 25
    assert splash.status_text == "加载核心库…"
    splash.update_progress(STAGE_LOADING_MODEL)
    assert splash.percent == 50
    assert splash.status_text == "加载手部模型…"
    splash.update_progress(STAGE_INIT_CAMERA)
    assert splash.percent == 75
    assert splash.status_text == "初始化摄像头…"
    splash.update_progress(STAGE_READY)
    assert splash.percent == 100
    assert splash.status_text == "完成"


def test_splash_complete_hides_or_signals():
    """Reaching the ``ready`` stage must emit the ``finished`` signal so
    the caller can transition off the splash."""
    from ppt_qt.pages.splash_page import STAGE_READY
    splash = _make_splash()
    seen = []
    splash.finished.connect(lambda: seen.append("done"))
    splash.update_progress(STAGE_READY)
    # Signal fires synchronously inside update_progress for the READY stage
    assert seen == ["done"]
    # Idempotent — calling ready twice still only emits once
    splash.update_progress(STAGE_READY)
    assert seen == ["done"]