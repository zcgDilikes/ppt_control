"""Tests for ppt_core.command_dispatcher — central routing for parsed WS messages."""

from __future__ import annotations

import threading

from ppt_core.command_dispatcher import CommandDispatcher


class FakeMouse:
    def __init__(self):
        self.deltas = []
        self.absolutes = []
        self.clicks = []

    def apply_delta(self, dx, dy):
        self.deltas.append((dx, dy))

    def set_absolute(self, x, y):
        self.absolutes.append((x, y))

    def click(self, count):
        self.clicks.append(count)


class FakePptExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, d):
        self.calls.append(d)


def test_dispatch_laser_delta():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "LASER", "dx": 0.1, "dy": -0.2})
    assert m.deltas == [(0.1, -0.2)]
    assert p.calls == []


def test_dispatch_laser_absolute():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "LASER", "x": 0.5, "y": 0.3})
    assert m.absolutes == [(0.5, 0.3)]


def test_dispatch_mouse_click_default_count_1():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "MOUSE_CLICK"})
    assert m.clicks == [1]


def test_dispatch_mouse_click_count_2():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "MOUSE_CLICK", "count": 2})
    assert m.clicks == [2]


def test_dispatch_next_page_routes_to_ppt():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "NEXT_PAGE"})
    assert p.calls == [{"cmd": "NEXT_PAGE"}]


def test_dispatch_file_arrived_calls_on_download():
    received = []

    def on_download(url):
        received.append(url)

    d = CommandDispatcher(FakeMouse(), FakePptExecutor(), on_download=on_download)
    d.dispatch({"cmd": "FILE_ARRIVED", "url": "/uploads/a.pptx"})
    assert received == ["/uploads/a.pptx"]


def test_dispatch_spotlight_show_calls_on_spotlight():
    received = []

    def on_spotlight(payload):
        received.append(payload)

    d = CommandDispatcher(FakeMouse(), FakePptExecutor(), on_spotlight=on_spotlight)
    d.dispatch({"cmd": "SPOTLIGHT_SHOW", "cx": 0.5, "cy": 0.5, "halfW": 0.1, "halfH": 0.1})
    assert len(received) == 1
    assert received[0]["cx"] == 0.5


def test_dispatch_spotlight_hide_calls_on_spotlight_with_none():
    received = []

    def on_spotlight(payload):
        received.append(payload)

    d = CommandDispatcher(FakeMouse(), FakePptExecutor(), on_spotlight=on_spotlight)
    d.dispatch({"cmd": "SPOTLIGHT_HIDE"})
    assert received == [None]


def test_dispatch_timer_overlay_routes():
    received = []

    def on_timer_overlay(cmd, payload):
        received.append((cmd, payload))

    d = CommandDispatcher(FakeMouse(), FakePptExecutor(), on_timer_overlay=on_timer_overlay)
    d.dispatch({"cmd": "TIMER_OVERLAY_SHOW", "mode": "countdown", "seconds": 60})
    assert received == [("TIMER_OVERLAY_SHOW", {"mode": "countdown", "seconds": 60})]


def test_dispatch_pc_window_minimize():
    minimized = []

    def on_minimize():
        minimized.append(True)

    d = CommandDispatcher(FakeMouse(), FakePptExecutor(), on_minimize=on_minimize)
    d.dispatch({"cmd": "PC_WINDOW_MINIMIZE"})
    assert minimized == [True]


def test_dispatch_unknown_cmd_ignored():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    d.dispatch({"cmd": "WHATEVER_NEW"})
    assert p.calls == []


def test_dispatch_many():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)
    n = d.dispatch_many(['{"cmd":"NEXT_PAGE"}', "bad", '{"cmd":"PREV_PAGE"}'])
    assert n == 2
    assert [c["cmd"] for c in p.calls] == ["NEXT_PAGE", "PREV_PAGE"]


def test_dispatch_is_thread_safe():
    m, p = FakeMouse(), FakePptExecutor()
    d = CommandDispatcher(m, p)

    def worker():
        for _ in range(100):
            d.dispatch({"cmd": "NEXT_PAGE"})

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(p.calls) == 400
