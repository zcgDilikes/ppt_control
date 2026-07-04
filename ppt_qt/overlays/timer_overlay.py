from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor, QPalette


def format_timer_label(total_sec: int) -> str:
    """Format seconds as 'MM:SS' or 'H:MM:SS' depending on duration."""
    total = max(0, int(total_sec))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class TimerOverlay(QWidget):
    """Fullscreen overlay showing a countdown or stopwatch."""

    MODE_HIDDEN = "hidden"
    MODE_COUNTDOWN = "countdown"
    MODE_STOPWATCH = "stopwatch"

    def __init__(self, parent=None):
        super().__init__(parent)
        # Window flags: frameless, always on top, tool (no taskbar entry)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        # Internal state
        self._mode = self.MODE_HIDDEN
        self._remaining = 0  # for countdown: seconds left
        self._elapsed = 0    # for stopwatch: seconds elapsed
        self._paused = False

        # Build the label layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()

        self.label = QLabel("", self)
        font = QFont("Segoe UI", 96, QFont.Bold)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("color: #ffffff; background: transparent;")
        layout.addWidget(self.label, 0, Qt.AlignCenter)
        layout.addStretch()

        self.setStyleSheet("background-color: #1a1a1a;")

        # Timer setup
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def show_countdown(self, seconds: int):
        """Show a countdown starting from the given number of seconds."""
        self._mode = self.MODE_COUNTDOWN
        self._remaining = max(0, int(seconds))
        self._elapsed = 0
        self._paused = False
        self._update_label_text()
        self._show_fullscreen()
        self._timer.start()

    def show_stopwatch(self, start_seconds: int = 0):
        """Show a stopwatch starting from the given number of seconds."""
        self._mode = self.MODE_STOPWATCH
        self._elapsed = max(0, int(start_seconds))
        self._remaining = 0
        self._paused = False
        self._update_label_text()
        self._show_fullscreen()
        self._timer.start()

    def hide_overlay(self):
        """Stop ticking and hide the overlay window."""
        self._timer.stop()
        self._mode = self.MODE_HIDDEN
        self.hide()

    def pause(self):
        """Pause the running timer (countdown or stopwatch)."""
        if self._mode == self.MODE_HIDDEN:
            return
        self._paused = True
        self._timer.stop()

    def resume(self):
        """Resume a paused timer."""
        if self._mode == self.MODE_HIDDEN:
            return
        self._paused = False
        self._timer.start()

    def reset(self, seconds: int = None):
        """Reset the timer; optionally restart countdown with new seconds."""
        if seconds is not None:
            self._remaining = max(0, int(seconds))
            self._elapsed = 0
            self._mode = self.MODE_COUNTDOWN
            self._paused = False
            self._update_label_text()
            self._show_fullscreen()
            self._timer.start()
            return
        # No new value: reset current mode to zero
        if self._mode == self.MODE_COUNTDOWN:
            self._remaining = 0
        elif self._mode == self.MODE_STOPWATCH:
            self._elapsed = 0
        self._update_label_text()

    # ---------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------

    def _show_fullscreen(self):
        # Fullscreen across available screens; default to primary screen
        screen = self.screen()
        if screen is None:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _on_tick(self):
        if self._paused:
            return
        if self._mode == self.MODE_COUNTDOWN:
            self._remaining -= 1
            if self._remaining <= 0:
                self._remaining = 0
                self._update_label_text()
                self._timer.stop()
                return
        elif self._mode == self.MODE_STOPWATCH:
            self._elapsed += 1
        self._update_label_text()

    def _update_label_text(self):
        if self._mode == self.MODE_COUNTDOWN:
            text = format_timer_label(self._remaining)
        elif self._mode == self.MODE_STOPWATCH:
            text = format_timer_label(self._elapsed)
        else:
            text = ""
        self.label.setText(text)

    # Expose format helper on the class for convenience
    format_timer_label = staticmethod(format_timer_label)
