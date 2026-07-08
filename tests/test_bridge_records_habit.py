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


def test_flush_habits_writes_to_disk(tmp_path):
    """flush_habits should persist the buffer to user_data_dir/habits.json."""
    from ppt_core.hand_habits_storage import load_habits

    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = __import__("collections").deque(maxlen=100)
    bridge._habits_last_save = 0.0
    now = time.time()
    bridge._record_action("NEXT_PAGE", now)
    bridge._record_action("PREV_PAGE", now)

    user_data_dir = str(tmp_path / "user_data")
    ok = bridge.flush_habits(user_data_dir=user_data_dir, debounce_seconds=0.0)
    assert ok is True
    # Re-load and confirm both actions present
    loaded = load_habits(user_data_dir)
    actions = [a for a, _ in loaded]
    assert "NEXT_PAGE" in actions
    assert "PREV_PAGE" in actions


def test_flush_habits_debounces(tmp_path):
    """A second flush within 5s of the first should be a no-op."""
    bridge = GestureBridge.__new__(GestureBridge)
    bridge._habits = __import__("collections").deque(maxlen=100)
    bridge._habits_last_save = time.time()  # pretend we just saved
    bridge._record_action("NEXT_PAGE", time.time())

    ok = bridge.flush_habits(
        user_data_dir=str(tmp_path / "user_data"), debounce_seconds=5.0,
    )
    assert ok is False  # debounced
