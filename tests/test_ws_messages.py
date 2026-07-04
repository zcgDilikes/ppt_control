"""Tests for ppt_core.ws_messages — JSON message parsing and command routing helpers."""

from __future__ import annotations

from ppt_core.ws_messages import (
    is_laser_delta,
    is_mouse_click,
    parse,
    serialize,
)


def test_parse_valid():
    d = parse('{"cmd":"NEXT_PAGE","roomId":"ABC123"}')
    assert d == {"cmd": "NEXT_PAGE", "roomId": "ABC123"}


def test_parse_invalid_json_returns_none():
    assert parse("not json") is None


def test_parse_missing_cmd_returns_none():
    assert parse('{"roomId":"X"}') is None


def test_parse_non_dict_returns_none():
    assert parse('[1,2,3]') is None


def test_serialize_roundtrip():
    obj = {"cmd": "LASER", "x": 0.5, "y": 0.3}
    s = serialize(obj)
    assert parse(s) == obj


def test_is_laser_delta_true():
    assert is_laser_delta({"cmd": "LASER", "dx": 0.1, "dy": 0.2}) is True


def test_is_laser_delta_false_when_absolute():
    assert is_laser_delta({"cmd": "LASER", "x": 0.5, "y": 0.3}) is False


def test_is_mouse_click_true():
    assert is_mouse_click({"cmd": "MOUSE_CLICK", "count": 1}) is True


def test_is_mouse_click_false():
    assert is_mouse_click({"cmd": "LASER"}) is False
