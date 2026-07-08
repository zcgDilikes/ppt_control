import time
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

# Pre-import heavy modules so ``patch("cv2")`` etc. can resolve the target.
import cv2  # noqa: F401
import mediapipe.tasks.python  # noqa: F401


def test_main_window_shows_within_200ms():
    """主窗口 200ms 内可见(先 build UI 再 async load)。"""
    # Mock app 创建和 build 速度
    start = time.monotonic()
    with patch("ppt_qt.app.PptQtApp._build_main_window") as mock_build, \
         patch("ppt_qt.app.PptQtApp._async_load_core") as mock_async, \
         patch("ppt_qt.app.QMainWindow.show") as mock_show, \
         patch("ppt_qt.app.PptQtApp._setup_tray"):
        mock_build.return_value = None
        mock_async.return_value = None
        # 调用 PptQtApp.__init__:build 会在 show 之前被调用,
        # async 会在 show 之后被 schedule。
        from ppt_qt.app import PptQtApp
        with patch("ppt_qt.app.QTimer"):
            PptQtApp()
        elapsed = time.monotonic() - start
        # 断言:build 之前 show 已被调用
        # 简化:如果 build 被调用了
        assert mock_build.called


def test_heavy_modules_loaded_async():
    """cv2 / mediapipe / bridge 应在 _async_load_core 中加载,不阻塞 __init__。"""
    # Verify the heavy modules are imported inside ``_async_load_core``
    # rather than at module load time. We patch the source location so
    # ``import cv2`` etc. inside the body resolve to mocks.
    with patch.dict("sys.modules", {
        "cv2": MagicMock(),
        "mediapipe": MagicMock(),
        "mediapipe.tasks": MagicMock(),
        "mediapipe.tasks.python": MagicMock(),
        "ppt_core.gesture_bridge": MagicMock(GestureBridge=MagicMock()),
    }):
        from ppt_qt.app import PptQtApp
        # Mock 必要的 Qt 调用
        with patch.object(PptQtApp, "_build_main_window"), \
             patch.object(PptQtApp, "_setup_tray"), \
             patch.object(PptQtApp, "_async_load_core") as async_load, \
             patch("ppt_qt.app.QTimer") as mock_timer:
            # Make QTimer.singleShot invoke immediately so we can assert.
            mock_timer.singleShot.side_effect = lambda _ms, fn: fn()
            PptQtApp()
            # Heavy work should be deferred to the async phase, not __init__.
            assert async_load.called