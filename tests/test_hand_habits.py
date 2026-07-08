import time
import tempfile
from pathlib import Path
from ppt_core.hand_habits import HabitAnalyzer
from ppt_core.hand_habits_storage import load_habits, save_habits


def test_analyzer_top_n_by_frequency():
    now = time.time()
    history = [
        ("NEXT_PAGE", now - 10),
        ("NEXT_PAGE", now - 20),
        ("NEXT_PAGE", now - 30),
        ("BLACK_SCREEN", now - 5),
        ("PREV_PAGE", now - 15),
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    assert top == ["NEXT_PAGE", "BLACK_SCREEN", "PREV_PAGE"]


def test_analyzer_excludes_system_commands():
    """OPEN_PPT/SCREENSHOT 不进 top-3,避免被推为推荐。"""
    now = time.time()
    history = [
        ("OPEN_PPT", now - 1),
        ("OPEN_PPT", now - 2),
        ("OPEN_PPT", now - 3),
        ("NEXT_PAGE", now - 4),
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    assert "OPEN_PPT" not in top
    assert "NEXT_PAGE" in top


def test_analyzer_filters_old_actions():
    """30 天前的动作不算入。"""
    now = time.time()
    history = [
        ("NEXT_PAGE", now - 86400 * 31),  # 31 天前
        ("PREV_PAGE", now - 60),         # 1 分钟前
        ("NEXT_PAGE", now - 30),         # 30 秒前
    ]
    analyzer = HabitAnalyzer(history)
    top = analyzer.top_n_actions(3)
    # 31 天前的 NEXT_PAGE 不算
    # 30 秒前 NEXT_PAGE + 1 分钟前 PREV_PAGE 应是 top-2
    assert set(top) == {"NEXT_PAGE", "PREV_PAGE"}


def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        now = time.time()
        actions = [("NEXT_PAGE", now - 10), ("BLACK_SCREEN", now - 5)]
        save_habits(tmp, actions)
        loaded = load_habits(tmp)
        assert loaded == actions


def test_load_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as tmp:
        assert load_habits(tmp) == []