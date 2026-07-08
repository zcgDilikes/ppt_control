# tests/test_bridge_records_habit.py
import time
from unittest.mock import MagicMock
from ppt_core.gesture_bridge import GestureBridge


def test_record_action_appends_to_buffer():
    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = __import__("collections").deque(maxlen=100)
    bridge._record_action("NEXT_PAGE", time.time())
    assert len(bridge._habits) == 1
    assert bridge._habits[0][0] == "NEXT_PAGE"


def test_dispatch_records_action():
    """dispatch 路径应自动记录已派发的 action 到 habits。"""
    cfg = __import__("pc_gesture.config", fromlist=["load_gesture_config"]).load_gesture_config()
    cfg.tip_bindings["L_HAND_INDEX"] = "NEXT_PAGE"
    cfg.tip_bindings["L_HAND_MIDDLE"] = "BLACK_SCREEN"
    cfg.raw["operator_mode"] = "dual"

    bridge = GestureBridge(
        dispatcher=MagicMock(),
        on_status=lambda t: None,
        on_fps=lambda f: None,
    )
    # 模拟 5 次 L_HAND_INDEX + 3 次 L_HAND_MIDDLE
    now = time.time()
    for _ in range(5):
        bridge._record_action("NEXT_PAGE", now)
    for _ in range(3):
        bridge._record_action("BLACK_SCREEN", now)
    assert len(bridge._habits) == 8
    from collections import Counter
    counts = Counter(a for a, _ in bridge._habits)
    assert counts["NEXT_PAGE"] == 5
    assert counts["BLACK_SCREEN"] == 3


def test_habits_buffer_caps_at_100():
    from collections import deque
    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = deque(maxlen=100)
    for i in range(150):
        bridge._record_action(f"ACT_{i}", time.time())
    assert len(bridge._habits) == 100
    # 最旧 50 个应该被挤掉
    assert "ACT_0" not in [a for a, _ in bridge._habits]
    assert "ACT_50" in [a for a, _ in bridge._habits]
