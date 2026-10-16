"""Qt-only charts; no web engine, no per-frame signals or unbounded history."""

from collections import deque
import time
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy


def number(value, suffix='', digits=1):
    return '不可用' if value is None else f'{float(value):.{digits}f}{suffix}'


class Trend(QWidget):
    def __init__(self, series, unit):
        super().__init__()
        self.series, self.unit = series, unit
        self.points = deque(maxlen=601)
        self.setMinimumHeight(155)

    def append(self, sample):
        now = time.monotonic()
        self.points.append((now, sample))
        while self.points and now - self.points[0][0] > 600:
            self.points.popleft()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#0b1728'))
        rect = QRectF(30, 24, max(1, self.width() - 38), self.height() - 53)
        maximum = max([1] + [float(row[key]) for _, row in self.points
                            for key, _, _ in self.series if row.get(key) is not None]) * 1.1
        painter.setPen(QColor('#53657c'))
        painter.drawText(3, 17, f'{maximum:.0f} {self.unit}')
        painter.drawText(30, self.height() - 24, '−10 分钟 → 现在')
        painter.drawRect(rect)
        end = self.points[-1][0] if self.points else time.monotonic()
        for index, (key, label, color) in enumerate(self.series):
            painter.setPen(QPen(QColor(color), 1.6))
            path, connected = QPainterPath(), False
            for at, row in self.points:
                value = row.get(key)
                if value is None:
                    connected = False
                    continue
                x = rect.right() - min(600, end - at) / 600 * rect.width()
                y = rect.bottom() - float(value) / maximum * rect.height()
                if connected:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                connected = True
            painter.drawPath(path)
            painter.drawText(8 + index * 67, self.height() - 6, label)
        painter.end()


def build_performance(window, layout):
    window.performance_note = QLabel('每秒采样 · 最近十分钟 · 不可用值不绘制曲线')
    window.performance_note.setWordWrap(True)
    window.performance_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout.addWidget(window.performance_note)
    window.fps_trend = Trend([('capture_fps', '采集', '#6de0b7'), ('encode_fps', '编码', '#e6b45f'),
        ('pc_decode_fps', '电脑解码', '#72b1ff'), ('qt_paint_fps', 'Qt 绘制', '#e48fe7')], 'fps')
    window.flow_trend = Trend([('rtsp_mbps', 'RTSP', '#6de0b7'), ('pc_session_mbps', '本订阅', '#72b1ff'),
                              ('nic_tx_mbps', '网口TX', '#e6b45f')], 'Mbit/s')
    layout.addWidget(window.fps_trend)
    layout.addWidget(window.flow_trend)
    window.performance_detail = QLabel('等待采样')
    window.performance_detail.setWordWrap(True)
    window.performance_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    window.performance_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(window.performance_detail)
    for title, callback in [('选择 CSV 保存目录', window.choose_performance_folder),
                            ('导出本次 CSV', window.export_performance),
                            ('打开 CSV 目录', window.open_performance_folder)]:
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
    layout.addStretch()
