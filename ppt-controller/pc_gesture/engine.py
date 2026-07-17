"""手势引擎：采集线程 + 推理回调 + 指令派发。"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from .camera import CameraCapture, opencv_available
from .config import GestureConfig, load_gesture_config, save_gesture_config
from .recognizer import GestureRecognizerWrapper, mediapipe_available
from .semantics import GestureSemantics


class GestureEngine:
    def __init__(
        self,
        dispatch_fn: Callable[[Dict[str, Any], str], None],
        on_status: Optional[Callable[[str], None]] = None,
        on_fps: Optional[Callable[[float], None]] = None,
        on_send_text: Optional[Callable[[], None]] = None,
    ):
        self._dispatch = dispatch_fn
        self._on_status = on_status
        self._on_fps = on_fps
        self._on_send_text = on_send_text
        self.cfg = load_gesture_config()
        self._semantics = GestureSemantics(self.cfg, on_send_text=on_send_text)
        self._recognizer: Optional[GestureRecognizerWrapper] = None
        self._camera: Optional[CameraCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = False
        self._last_frame_ts = 0.0
        self._fps_counter = 0
        self._fps_last = time.monotonic()

    @property
    def running(self) -> bool:
        return self._running

    def reload_config(self) -> GestureConfig:
        self.cfg = load_gesture_config()
        self._semantics.reload_config(self.cfg)
        return self.cfg

    def save_config(self) -> None:
        save_gesture_config(self.cfg)

    def start(self) -> str:
        if self._running:
            return "已在运行"
        if not opencv_available():
            return "请安装 opencv-python"
        if not mediapipe_available():
            return "请安装 mediapipe"
        self.reload_config()
        self._stop.clear()
        try:
            self._recognizer = GestureRecognizerWrapper(num_hands=self.cfg.num_hands())
            self._camera = CameraCapture(
                index=int(self.cfg.raw.get("camera_index") or 0),
                mirror=bool(self.cfg.raw.get("mirror", True)),
            )
            self._camera.open()
        except Exception as e:
            self._cleanup_devices()
            return str(e)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._status("手势识别已启动")
        return ""

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._cleanup_devices()
        self._status("手势识别已停止")

    def _cleanup_devices(self) -> None:
        if self._recognizer:
            try:
                self._recognizer.close()
            except Exception:
                pass
            self._recognizer = None
        if self._camera:
            try:
                self._camera.release()
            except Exception:
                pass
            self._camera = None

    def _status(self, msg: str) -> None:
        if self._on_status:
            try:
                self._on_status(msg)
            except Exception:
                pass

    def _loop(self) -> None:
        skip = 0
        while not self._stop.is_set():
            if self._camera is None or self._recognizer is None:
                break
            ok, frame = self._camera.read()
            if not ok:
                time.sleep(0.05)
                continue
            ts_ms = int(time.time() * 1000)
            self._recognizer.detect_async(frame, ts_ms)
            time.sleep(0.001)
            result = self._recognizer.poll_latest()
            if result.timestamp_ms <= self._last_frame_ts and not result.hands:
                time.sleep(0.005)
                continue
            self._last_frame_ts = result.timestamp_ms
            skip += 1
            if skip % 1 != 0:
                continue
            sem = self._semantics.process_frame(result)
            if sem.status:
                self._status(sem.status)
            preview_only = self.cfg.preview_only or not self.cfg.enabled
            if not preview_only:
                for cmd in sem.commands:
                    try:
                        self._dispatch(cmd, "gesture")
                    except Exception:
                        pass
            self._fps_counter += 1
            now = time.monotonic()
            if now - self._fps_last >= 1.0:
                fps = self._fps_counter / (now - self._fps_last)
                self._fps_counter = 0
                self._fps_last = now
                if self._on_fps:
                    try:
                        self._on_fps(fps)
                    except Exception:
                        pass
            time.sleep(0.005)
        self._running = False

    def start_pairing(self) -> None:
        self._semantics.operator_mgr.start_pairing()

    def reset_pairing(self) -> None:
        self._semantics.operator_mgr.reset_pairing()

    def toggle_swap_roles(self) -> bool:
        self.cfg.raw["dual_roles_swapped"] = not self.cfg.raw.get("dual_roles_swapped")
        self.save_config()
        return bool(self.cfg.raw["dual_roles_swapped"])
