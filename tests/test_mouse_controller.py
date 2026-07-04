"""Tests for ppt_core.mouse_controller — synchronous mouse dispatch."""

from __future__ import annotations

import threading

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


class FakeController:
    def __init__(self):
        self.moves = []      # list of (dx, dy)
        self.positions = []  # list of (x, y)
        self.clicks = 0

    def move(self, dx, dy):
        self.moves.append((dx, dy))

    @property
    def position(self):
        return None

    @position.setter
    def position(self, value):
        self.positions.append(value)

    def click(self, button):
        self.clicks += 1


class FakeButton:
    left = "left"


@pytest.fixture
def fake_pg(monkeypatch):
    pg = FakePyautogui()
    import ppt_core.mouse_controller as mod
    monkeypatch.setattr(mod, "pyautogui", pg)

    # Provide a fake pynput module so MouseController can import it lazily.
    import sys
    import types

    fake_pynput = types.ModuleType("pynput")
    fake_pynput_mouse = types.ModuleType("pynput.mouse")

    fc = FakeController()
    fake_pynput_mouse.Controller = lambda: fc
    fake_pynput_mouse.Button = FakeButton
    fake_pynput.mouse = fake_pynput_mouse
    monkeypatch.setitem(sys.modules, "pynput", fake_pynput)
    monkeypatch.setitem(sys.modules, "pynput.mouse", fake_pynput_mouse)

    return pg, fc


def test_apply_delta_synchronous_moves_cursor(fake_pg):
    from ppt_core.mouse_controller import MouseController
    _pg, fc = fake_pg
    m = MouseController()
    m.apply_delta(0.1, -0.2)
    # dx=0.1 * LASER_SENS(6) = 0.6 ; dy=-0.2 * 6 = -1.2
    assert fc.moves == [(1, -1)]  # rounded to int


def test_apply_delta_concurrent_no_loss(fake_pg):
    from ppt_core.mouse_controller import MouseController
    _pg, fc = fake_pg
    m = MouseController()
    def w():
        for _ in range(500):
            m.apply_delta(0.01, 0.01)
    threads = [threading.Thread(target=w) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Each thread contributes 500 moves; total should be 2000.
    assert len(fc.moves) == 2000


def test_set_absolute_to_pixel(fake_pg):
    from ppt_core.mouse_controller import MouseController
    pg, fc = fake_pg
    m = MouseController()
    m.set_absolute(0.5, 0.25)
    assert pg.jumps == [(960, 270)]
    assert fc.positions == [(960, 270)]


def test_click_default_1(fake_pg):
    from ppt_core.mouse_controller import MouseController
    pg, fc = fake_pg
    m = MouseController()
    m.click()
    assert pg.clicks == [1]
    assert fc.clicks == 1


def test_click_count_2(fake_pg):
    from ppt_core.mouse_controller import MouseController
    pg, fc = fake_pg
    m = MouseController()
    m.click(2)
    assert pg.clicks == [2]
    assert fc.clicks == 2
