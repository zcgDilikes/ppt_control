"""摄像头采集。"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

_HAS_CV = False
try:
    import cv2

    _HAS_CV = True
except ImportError:
    cv2 = None


def opencv_available() -> bool:
    return _HAS_CV


class CameraCapture:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480, mirror: bool = True):
        if not _HAS_CV:
            raise RuntimeError("未安装 opencv-python")
        self.index = index
        self.width = width
        self.height = height
        self.mirror = mirror
        self._cap = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 index={self.index}")

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self._cap is None:
            return False, None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return False, None
        if self.mirror:
            frame = cv2.flip(frame, 1)
        return True, frame

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
