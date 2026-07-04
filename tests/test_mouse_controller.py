"""Tests for ppt_core.mouse_controller — delta/click queue + pyautogui bridge."""

from __future__ import annotations

import pytest


class FakePyautogui:
    def __init__(self):
        self.size = (1920, 1080)
        self.jumps = []
        self.clicks = []

    def size(self):
        return self.size

    def move(self, dx, dy):
        self.jumps.append((dx, dy))

    def position(self, x, y):
        self.jumps.append((x, y))

    def click(self, button, n):
        self.clicks.append(n)


@pytest.fixture
def fake_pg(monkeypatch):
    pg = FakePyautogui()
    import ppt_core.mouse_controller as mod
    monkeypatch.setattr(mod, "pyautogui", pg)
    return pg


def test_apply_delta_uses_sens(fake_pg):
    from ppt_core.mouse_controller import MouseController
    m = MouseController()
    m.apply_delta(0.1, -0.2)
    flush = m.flush_deltas()
    assert flush == [(0.6, -1.2)]
    assert m.flush_deltas() == []


def test_set_absolute_to_pixel(fake_pg):
    from ppt_core.mouse_controller import MouseController
    m = MouseController()
    m.set_absolute(0.5, 0.25)
    assert fake_pg.jumps == [(960, 270)]


def test_click_default_1(fake_pg):
    from ppt_core.mouse_controller import MouseController
    m = MouseController()
    m.click()
    assert fake_pg.clicks == [1]
    assert m.pending_clicks() == []


def test_click_count_2(fake_pg):
    from ppt_core.mouse_controller import MouseController
    m = MouseController()
    m.click(2)
    assert fake_pg.clicks == [2]


def test_thread_safe_deltas():
    import threading
    from ppt_core.mouse_controller import MouseController
    m = MouseController()
    def w():
        for _ in range(500):
            m.apply_delta(0.01, 0.01)
    threads = [threading.Thread(target=w) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    flush = m.flush_deltas()
    assert len(flush) == 2000