"""PptQtApp: composition root. Wires ppt_core + ppt_qt."""
from __future__ import annotations
import os
import subprocess
import sys
import json
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtCore import Qt, QSize, QTimer, QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QColor, QPixmap

from ppt_core.settings import DEFAULT_SETTINGS, load_settings, save_settings
from ppt_core.room import load_or_create_room_id
from ppt_core.command_dispatcher import CommandDispatcher
from ppt_core.mouse_controller import MouseController
from ppt_core.ppt_executor import PptExecutor
from ppt_core.ppt_notes import PptNotesWorker
from ppt_core.downloads import DownloadManager
from ppt_core.ws_client import WsClient
from ppt_core.gesture_bridge import GestureBridge
from ppt_qt.theme import GLOBAL_QSS
from ppt_qt.widgets import Sidebar, StatusPill, GlassCard, PrimaryButton, SecondaryButton, BackgroundWidget
from ppt_qt.overlays.spotlight import SpotlightOverlay
from ppt_qt.overlays.timer_overlay import TimerOverlay
from ppt_qt.pages import ConnectPage, BehaviorPage, TransfersPage, GesturePage
from ppt_qt.pages.splash_page import (
    SplashPage, STAGE_IMPORTING, STAGE_LOADING_MODEL,
    STAGE_INIT_CAMERA, STAGE_READY,
)
from ppt_qt.bridge import QtBridge

SERVER_BASE = "https://ppt.dilikes.com"
PPT_PC_WS_SUBPATH = "ws/python"


class PptQtApp(QObject):
    # Emitted when the async core load finishes (Phase 2 done). UI may
    # safely wire up gesture / capture pipelines once this fires.
    core_ready = Signal()

    def __init__(self):
        super().__init__()
        self._settings = load_settings()
        self._room_id = load_or_create_room_id()

        # Bridge: workers / asyncio thread ``emit`` on these Signals; Qt
        # auto-delivers them on the main thread via QueuedConnection.
        self._qt = QtBridge()

        self._mouse = MouseController()
        self._ppt = PptExecutor(on_screenshot=self._on_screenshot)
        self._dispatcher = CommandDispatcher(
            self._mouse, self._ppt,
            on_download=lambda url: self._qt.emit_file_arrived(url),
            on_spotlight=lambda payload: self._qt.emit_spotlight(payload),
            on_timer_overlay=self._on_timer_overlay,
            on_minimize=self._on_window_minimize,
            on_restore=self._on_window_restore,
            on_client_settings=self._on_client_settings,
        )
        self._downloads = DownloadManager(
            base_url=SERVER_BASE, save_dir="./ppt_files/",
            on_record_added=lambda rec: self._qt.emit_record_added(rec),
            on_ppt_open=self._on_ppt_downloaded,
        )

        # Build the QApplication first; main window construction references
        # ``self._gesture_page`` which is initialised in ``_build_main_window``.
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyleSheet(GLOBAL_QSS)

        # GestureBridge needs ``self._gesture_page`` callbacks, but its public
        # methods are not called until after ``_build_main_window`` runs.
        # We construct a placeholder here and patch callbacks below.
        self._bridge = GestureBridge(
            dispatcher=self._dispatcher,
            on_status=lambda text: None,
            on_fps=lambda fps: None,
        )

        self._build_main_window()
        self._ws = None

        # Now that ``self._gesture_page`` exists, rewire the bridge callbacks.
        self._bridge._on_status = lambda text: self._gesture_page.set_status(text)
        self._bridge._on_fps = lambda fps: self._gesture_page.set_fps(fps)

        # Connect bridge signals to GUI-thread slots.
        self._qt.ws_status.connect(self._on_ws_status)
        self._qt.ws_connected.connect(self._on_ws_connected)
        self._qt.ws_disconnected.connect(self._on_ws_disconnected)
        self._qt.ws_fatal_disconnect.connect(self._on_ws_fatal)
        self._qt.file_arrived.connect(self._on_file_arrived)
        self._qt.record_added.connect(self._on_record_added)
        self._qt.notes_send.connect(self._on_notes_send)
        self._qt.mobile_presence.connect(self._on_mobile_presence)
        self._qt.spotlight.connect(self._on_spotlight)

        # PPT notes COM worker (independent thread, no Qt dependency).
        self._notes = PptNotesWorker(
            send_fn=lambda payload: self._qt.emit_notes_send(payload),
            get_settings=lambda: self._settings,
        )
        self._notes.start()

        self._setup_tray()

        # Phase 2: async-load heavy modules (cv2/mediapipe/bridge) so
        # the main window can render under 200ms without waiting for
        # MediaPipe's slow first import.
        QTimer.singleShot(0, self._async_load_core)

    def _async_load_core(self):
        """后台线程加载 cv2 / mediapipe / bridge(防 import 阻塞首启)。

        Stub for Task 4 — just verifies imports succeed and emits
        ``core_ready``. Phase 5 will replace the body with the real
        engine + camera bootstrap.

        Drives the splash through its 4 stages (plan §2.3).
        """
        try:
            self._splash_update(STAGE_IMPORTING)
            import cv2  # noqa: F401
            from mediapipe.tasks import python  # noqa: F401
            from mediapipe.tasks.python import vision  # noqa: F401
            self._splash_update(STAGE_LOADING_MODEL)
            # Model load: try to import engine module (cheap, but logically
            # maps to "ready to construct landmarker").
            from pc_gesture.engine import GestureEngine  # noqa: F401
            self._splash_update(STAGE_INIT_CAMERA)
            # Probe camera availability — if absent, just log; the engine
            # itself handles the open failure later.
            try:
                cap = cv2.VideoCapture(self._settings.get("camera_index", 0))
                cap_opened = bool(cap.isOpened())
                cap.release()
            except Exception:
                cap_opened = False
            self._splash_update(STAGE_READY)
            self.core_ready.emit()
        except Exception as e:
            self._safe_status(f"初始化失败:{e}")
            # Still advance to READY so the splash doesn't hang.
            try:
                self._splash_update(STAGE_READY)
            except Exception:
                pass

    def _splash_update(self, stage: str) -> None:
        """Plan §2.3: push a stage to the splash if it exists."""
        try:
            splash = getattr(self, "_splash", None)
            if splash is not None:
                splash.update_progress(stage)
        except Exception:
            pass

    def _safe_status(self, text: str) -> None:
        """Update the status pill if the UI is up; swallow errors otherwise.

        Used during async core load when the main window may not be
        fully realised yet.
        """
        try:
            pill = getattr(self, "_status_pill", None)
            if pill is not None:
                pill.set_status(text)
        except Exception:
            pass

    def _build_main_window(self):
        self._win = QMainWindow()
        self._win.setWindowTitle("PPT 遥控")
        self._win.setMinimumSize(620, 620)
        self._win.resize(780, 780)
        # Plan §2.3: brief splash with 4-stage progress ring.
        # Lives in its own QStackedWidget; once ``core_ready`` fires,
        # we swap to the main background widget.
        self._outer_stack = QStackedWidget()
        self._win.setCentralWidget(self._outer_stack)
        self._splash = SplashPage()
        self._outer_stack.addWidget(self._splash)

        central = BackgroundWidget()
        central.setMinimumSize(620, 620)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._sidebar = Sidebar(
            items=[("连接","⌂"),("行为","⚙"),("传输","↥"),("手势","✋")],
            current=0, on_change=self._on_page_changed,
            on_exit=self._quit_app,
        )
        h.addWidget(self._sidebar)
        right = QWidget()
        v = QVBoxLayout(right)
        v.setContentsMargins(20, 20, 20, 12)
        v.setSpacing(12)
        self._status_pill = StatusPill(
            status_text="就绪 · 未连接", button_text="启动服务",
            on_button=self._on_toggle_service,
        )
        v.addWidget(self._status_pill)
        self._stack = QStackedWidget()
        self._connect_page = ConnectPage(room_id=self._room_id, on_toggle_service=self._on_toggle_service)
        self._behavior_page = BehaviorPage(settings=self._settings, on_change=self._on_settings_changed)
        self._transfers_page = TransfersPage(on_reveal=self._on_reveal_selected, on_open_dir=self._on_open_save_dir)
        self._gesture_page = GesturePage(bridge=self._bridge)
        for p in (self._connect_page, self._behavior_page, self._transfers_page, self._gesture_page):
            self._stack.addWidget(p)
        v.addWidget(self._stack, 1)
        h.addWidget(right, 1)
        self._outer_stack.addWidget(central)

        # When core load finishes, drop the splash.
        self.core_ready.connect(self._on_core_ready_swap_to_main)
        self._spotlight = SpotlightOverlay()
        self._timer_overlay = TimerOverlay()

    def _on_core_ready_swap_to_main(self) -> None:
        """Plan §2.3: once core is loaded, swap splash out for main UI."""
        try:
            if getattr(self, "_outer_stack", None) is not None:
                # Index 1 = central; index 0 = splash.
                self._outer_stack.setCurrentIndex(1)
        except Exception:
            pass

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon()
        pix = QPixmap(32, 32)
        pix.fill(QColor("#ff6e7f"))
        icon.addPixmap(pix)
        self._tray = QSystemTrayIcon(icon, parent=self._app)
        menu = QMenu()
        menu.addAction(QAction("显示主窗口", self._app, triggered=self._win.showNormal))
        menu.addAction(QAction("退出", self._app, triggered=self._quit_app))
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _on_page_changed(self, idx):
        self._stack.setCurrentIndex(idx)

    def _on_toggle_service(self):
        if self._ws is not None and self._ws.isRunning():
            self._ws.stop()
            self._status_pill.set_status("正在断开…")
            self._status_pill.set_button_text("启动服务")
            self._connect_page.set_running(False)
        else:
            self._ws = WsClient(
                base_url=SERVER_BASE, sub_path=PPT_PC_WS_SUBPATH, room_id=self._room_id,
                on_message=lambda d: self._dispatcher.dispatch(d),
                on_status=lambda t: self._qt.emit_ws_status(t),
                on_connected=lambda: self._qt.emit_ws_connected(),
                on_disconnected=lambda err: self._qt.emit_ws_disconnected(err),
                on_fatal_disconnect=lambda err, n: self._qt.emit_ws_fatal(err, n),
                on_mobile_presence=lambda online: self._qt.emit_mobile_presence(online),
            )
            self._ws.start()
            self._status_pill.set_status("正在连接服务器…")
            self._status_pill.set_button_text("停止服务")
            self._connect_page.set_running(True)

    # ----- WS / bridge handlers (Qt main thread via QueuedConnection) -----

    def _on_ws_status(self, text):
        self._status_pill.set_status(text)

    def _on_ws_connected(self):
        self._status_pill.set_ok(True)
        self._status_pill.set_status("已连接 · 等待手机端指令")

    def _on_ws_disconnected(self, _err):
        self._status_pill.set_ok(False)
        self._status_pill.set_status("已断开")

    def _on_ws_fatal(self, err, attempts):
        QMessageBox.warning(
            self._win,
            "连接失败",
            f"{attempts} 次重连失败：{err}\n请检查网络后点击启动服务重试",
        )

    def _on_file_arrived(self, url):
        self._downloads.enqueue(url)

    def _on_record_added(self, _rec):
        self._transfers_page.set_records(self._downloads.records())

    def _on_screenshot(self, path):
        if not self._settings.get("screenshot_open_folder", True):
            return
        try:
            subprocess.run(
                ["explorer", "/select,", os.path.normpath(path)],
                check=False,
            )
        except Exception:
            pass

    def _on_ppt_downloaded(self, path):
        if not self._settings.get("transfer_open_ppt", True):
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_notes_send(self, payload):
        if self._ws is None:
            return
        try:
            self._ws.send({**payload, "roomId": self._room_id})
        except Exception:
            pass

    def _on_mobile_presence(self, online: bool) -> None:
        # Sync the home page mobile pill with phone ONLINE/OFFLINE.
        self._connect_page.set_mobile_online(bool(online))

    def _on_settings_changed(self, new_settings):
        self._settings = new_settings
        save_settings(self._settings)
        self._broadcast_settings()
        try:
            self._notes.request_refresh()
        except Exception:
            pass

    def _broadcast_settings(self):
        if self._ws is None:
            return
        payload = dict(self._settings, roomId=self._room_id, cmd="CLIENT_SETTINGS")
        try:
            self._ws.send(payload)
        except Exception:
            pass

    def _on_client_settings(self, d):
        for k in ("screenshot_open_folder","transfer_open_folder","transfer_open_ppt","ppt_notes_enabled"):
            if k in d:
                self._settings[k] = bool(d[k])
        if "open_ppt_path" in d:
            self._settings["open_ppt_path"] = str(d["open_ppt_path"] or "")
        save_settings(self._settings)
        self._behavior_page.reload_from_model()
        self._broadcast_settings()

    def _on_spotlight(self, payload):
        if payload is None:
            self._spotlight.hide_overlay()
            return
        cx = float(payload.get("cx", 0.5)); cy = float(payload.get("cy", 0.5))
        hw = float(payload.get("halfW", 0.075)); hh = float(payload.get("halfH", 0.06))
        if not self._spotlight.isVisible():
            self._spotlight.showFullScreen()
        self._spotlight.apply(cx, cy, hw, hh)

    def _on_timer_overlay(self, cmd, d):
        if cmd == "TIMER_OVERLAY_SHOW":
            sec = int(d.get("seconds", 0))
            mode = str(d.get("mode", "countdown"))
            if mode == "stopwatch":
                self._timer_overlay.show_stopwatch(sec)
            else:
                self._timer_overlay.show_countdown(sec)
        elif cmd == "TIMER_OVERLAY_HIDE":
            self._timer_overlay.hide_overlay()
        elif cmd == "TIMER_OVERLAY_PAUSE":
            self._timer_overlay.pause()
        elif cmd == "TIMER_OVERLAY_RESUME":
            self._timer_overlay.resume()
        elif cmd == "TIMER_OVERLAY_RESET":
            sec = int(d.get("seconds", 0))
            self._timer_overlay.reset(sec)

    def _on_window_minimize(self):
        self._win.showMinimized()

    def _on_window_restore(self):
        self._win.showNormal()

    def _on_reveal_selected(self, idx):
        records = self._downloads.records()
        if 0 <= idx < len(records):
            self._downloads.reveal(records[idx]["path"])

    def _on_open_save_dir(self):
        self._downloads.open_folder()

    def _quit_app(self):
        # error.txt [16]:逐个 stop + join 避免 C++ 对象删除后子线程还在 emit
        if self._ws is not None:
            try:
                self._ws.stop()
            except Exception:
                pass
            try:
                self._ws.join(timeout=1.5)
            except Exception:
                pass
        try:
            self._bridge.stop()
        except Exception:
            pass
        try:
            self._notes.stop()
            # notes worker 是 PptNotesWorker 实例,有 _thread
            t = getattr(self._notes, "_thread", None)
            if t is not None and t.is_alive():
                t.join(timeout=1.5)
        except Exception:
            pass
        self._win.close()
        self._app.quit()

    def run(self):
        self._win.show()
        return self._app.exec()
