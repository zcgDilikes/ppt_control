"""PptQtApp: composition root. Wires ppt_core + ppt_qt."""
from __future__ import annotations
import os
import subprocess
import sys
import json
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtCore import Qt, QSize
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
from ppt_qt.bridge import QtBridge

SERVER_BASE = "https://ppt.dilikes.com"
PPT_PC_WS_SUBPATH = "ws/python"


class PptQtApp:
    def __init__(self):
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
            on_spotlight=self._on_spotlight,
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

        # Build the QApplication + main window BEFORE connecting bridge signals
        # so that ``self._win`` is valid when slots fire.
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyleSheet(GLOBAL_QSS)
        self._build_main_window()
        self._ws = None

        # Connect bridge signals to GUI-thread slots.
        self._qt.ws_status.connect(self._on_ws_status)
        self._qt.ws_connected.connect(self._on_ws_connected)
        self._qt.ws_disconnected.connect(self._on_ws_disconnected)
        self._qt.ws_fatal_disconnect.connect(self._on_ws_fatal)
        self._qt.file_arrived.connect(self._on_file_arrived)
        self._qt.record_added.connect(self._on_record_added)
        self._qt.notes_send.connect(self._on_notes_send)

        self._bridge = GestureBridge(
            dispatcher=self._dispatcher,
            on_status=lambda text: self._gesture_page.set_status(text),
            on_fps=lambda fps: self._gesture_page.set_fps(fps),
            on_send_text=self._on_gesture_send_text,
        )

        # PPT notes COM worker (independent thread, no Qt dependency).
        self._notes = PptNotesWorker(
            send_fn=lambda payload: self._qt.emit_notes_send(payload),
            get_settings=lambda: self._settings,
        )
        self._notes.start()

        self._setup_tray()

    def _build_main_window(self):
        self._win = QMainWindow()
        self._win.setWindowTitle("PPT 遥控")
        self._win.setMinimumSize(620, 620)
        self._win.resize(780, 780)
        central = BackgroundWidget()
        central.setMinimumSize(620, 620)
        self._win.setCentralWidget(central)
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
        self._spotlight = SpotlightOverlay()
        self._timer_overlay = TimerOverlay()

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

    def _on_gesture_send_text(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self._win, "发文本", "输入要发送到前台的文本：")
        if ok and text:
            self._dispatcher.dispatch({"cmd": "SEND_TEXT", "text": text})

    def _quit_app(self):
        if self._ws is not None:
            self._ws.stop()
        try:
            self._bridge.stop()
        except Exception:
            pass
        try:
            self._notes.stop()
        except Exception:
            pass
        self._win.close()
        self._app.quit()

    def run(self):
        self._win.show()
        return self._app.exec()
