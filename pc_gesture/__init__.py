"""
pc_gesture — PPT 遥控手势识别包。

入口：
    GestureEngine（engine.py）
    load_gesture_config / save_gesture_config / GestureConfig（config.py）

依赖：
    pip install opencv-python mediapipe
首次运行会自动从 Google Storage 下载 hand_landmarker.task（约 5MB）到
pc_gesture_models/ 目录；如离线需自行放置同名模型文件。
"""
from .config import GestureConfig, load_gesture_config, save_gesture_config
from .engine import GestureEngine

__all__ = ["GestureEngine", "GestureConfig", "load_gesture_config", "save_gesture_config"]