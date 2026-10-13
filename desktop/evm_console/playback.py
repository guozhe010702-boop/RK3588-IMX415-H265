"""Local MP4 playback dialog; owns only its Windows decoder and frame timer."""

from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
from .video import VideoWorker
from .widgets import VideoCanvas


class LocalVideoDialog(QDialog):
    def __init__(self, path, parent):
        super().__init__(parent)
        self.setWindowTitle("录像回放 · " + Path(path).name)
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        self.canvas = VideoCanvas()
        layout.addWidget(self.canvas, 1)
        layout.addWidget(QLabel("本地 MP4 循环回放 · 关闭窗口结束播放"))
        self.worker = VideoWorker()
        self.worker.state.connect(self.canvas.set_message)
        self.worker.configure(path, 1280, 720, ("file", 1280, 720, path))
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.render)
        self.timer.start()

    def render(self):
        frame = self.worker.take_frame()
        if frame:
            self.canvas.set_frame(frame[0], frame[1], frame[2])

    def closeEvent(self, event):
        self.timer.stop()
        self.worker.shutdown()
        if not self.worker.isRunning():
            parent = self.parent()
            if (
                parent is not None
                and hasattr(parent, "file_viewers")
                and self in parent.file_viewers
            ):
                parent.file_viewers.remove(self)
            event.accept()
            self.deleteLater()
        else:
            event.ignore()
            if not hasattr(self, "close_timer"):
                self.close_timer = QTimer(self)
                self.close_timer.setInterval(100)
                self.close_timer.timeout.connect(self.close_if_ready)
                self.close_timer.start()

    def close_if_ready(self):
        if not self.worker.isRunning():
            self.close_timer.stop()
            self.close()
