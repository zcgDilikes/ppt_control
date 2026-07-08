"""Tests for P0.2: GestureSemantics.interlock_progress 方法。"""


def test_interlock_progress_zero_when_not_started():
    from pc_gesture.config import load_gesture_config
    from pc_gesture.semantics import GestureSemantics
    import time
    sem = GestureSemantics(load_gesture_config())
    assert sem.interlock_progress(time.monotonic()) == 0.0


def test_interlock_progress_clamped_to_one():
    from pc_gesture.config import load_gesture_config
    from pc_gesture.semantics import GestureSemantics
    import time
    sem = GestureSemantics(load_gesture_config())
    sem._interlock_start = time.monotonic() - 100.0  # 100s 前
    progress = sem.interlock_progress(time.monotonic())
    assert progress == 1.0


def test_interlock_progress_increases_over_time():
    from pc_gesture.config import load_gesture_config
    from pc_gesture.semantics import GestureSemantics
    import time
    sem = GestureSemantics(load_gesture_config())
    sem.cfg.sensitivity["interlock_min_dwell_s"] = 1.0  # 1s dwell
    # 起点
    t0 = time.monotonic()
    sem._interlock_start = t0
    # 0.5s 后:50% 完成
    progress = sem.interlock_progress(t0 + 0.5)
    assert 0.4 < progress < 0.6
    # 1.5s 后:超过 dwell,封顶 1.0
    progress2 = sem.interlock_progress(t0 + 1.5)
    assert progress2 == 1.0


def test_interlock_progress_handles_invalid_dwell():
    """sensitivity 配错时 fallback 到 2.0s 默认。"""
    from pc_gesture.config import load_gesture_config
    from pc_gesture.semantics import GestureSemantics
    import time
    sem = GestureSemantics(load_gesture_config())
    sem.cfg.sensitivity["interlock_min_dwell_s"] = "not a number"
    sem._interlock_start = time.monotonic() - 4.0  # 4s 前
    progress = sem.interlock_progress(time.monotonic())
    # fallback dwell = 2.0,4s 进度 2.0 → 1.0
    assert progress == 1.0
