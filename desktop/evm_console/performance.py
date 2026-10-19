"""Qt-only charts; no web engine, no per-frame signals or unbounded history."""

from collections import deque
import math
import time
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath, QTextOption
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
                              QTextEdit, QFrame, QGridLayout, QProgressBar)


def number(value, suffix='', digits=1):
    return '不可用' if value is None else f'{float(value):.{digits}f}{suffix}'


class WrappingDetails(QTextEdit):
    """Selectable plain text; wrap long paths without altering their copy value.

    Height follows the document so the surrounding page owns the only vertical
    scrollbar. QLabel's word wrapping can clip an unbroken Windows path.
    """
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QTextEdit { background:transparent; border:0; }")
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.setPlainText("等待采样")

    def fit_height(self, *_):
        height = max(24, math.ceil(self.document().size().height()) + 4)
        if self.size().height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.fit_height)


def time_label(seconds):
    return f'{seconds / 60:.1f} 分钟前' if seconds >= 60 else f'{seconds:.0f} 秒前'


class TrendPlot(QWidget):
    def __init__(self, trend):
        super().__init__()
        self.trend = trend
        self.setMinimumHeight(145)
        self.setMinimumWidth(100)

    def geometry_for_plot(self):
        # Axis labels have their own bottom margin, outside the data rectangle.
        return QRectF(38, 10, max(1, self.width()-48), max(1, self.height()-44))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#0b1728'))
        trend, rect = self.trend, self.geometry_for_plot()
        values = [float(row[key]) for _, row in trend.points
            for key, _, _ in trend.series if row.get(key) is not None]
        upper = max([1] + values) * 1.1
        step = 10 ** math.floor(math.log10(upper))
        maximum = math.ceil(upper/step)*step
        end = trend.points[-1][0] if trend.points else time.monotonic()
        elapsed = end-trend.points[0][0] if trend.points else 0
        span = max(30, min(600, elapsed))
        painter.setPen(QPen(QColor('#293e58'), 1))
        for fraction in (0, 0.5, 1):
            y = rect.bottom()-fraction*rect.height()
            painter.drawLine(rect.left(), y, rect.right(), y)
            painter.setPen(QColor('#8a9bb2'))
            painter.drawText(QRectF(0, y-9, 33, 18), Qt.AlignmentFlag.AlignRight, f'{maximum*fraction:g}')
            painter.setPen(QPen(QColor('#293e58'), 1))
        painter.drawRect(rect)
        if not values:
            painter.setPen(QColor('#8a9bb2'))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '等待有效采样')
        # Text is below the border with 7px separation; never inside the plot.
        painter.setPen(QColor('#8a9bb2'))
        painter.drawText(QRectF(rect.left(), rect.bottom()+7, rect.width()/2, 22),
                         Qt.AlignmentFlag.AlignLeft, time_label(span))
        painter.drawText(QRectF(rect.center().x()-36, rect.bottom()+7, 72, 22),
                         Qt.AlignmentFlag.AlignHCenter, time_label(span/2))
        painter.drawText(QRectF(rect.right()-45, rect.bottom()+7, 45, 22),
                         Qt.AlignmentFlag.AlignRight, '现在')
        painter.save()
        painter.setClipRect(rect)
        for key, _, color in trend.series:
            painter.setPen(QPen(QColor(color), 1.6))
            path, connected = QPainterPath(), False
            for at, row in trend.points:
                value = row.get(key)
                if value is None:
                    connected = False
                    continue
                x = rect.right()-min(span, end-at)/span*rect.width()
                y = rect.bottom()-float(value)/maximum*rect.height()
                if connected:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                connected = True
            painter.drawPath(path)
        painter.restore()
        painter.end()


class Trend(QWidget):
    def __init__(self, series, unit):
        super().__init__()
        self.series, self.unit = series, unit
        self.points = deque(maxlen=601)
        self.started_at = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.heading = QLabel('帧率趋势 · fps' if unit == 'fps' else '流速趋势 · Mbit/s')
        layout.addWidget(self.heading)
        self.plot = TrendPlot(self)
        layout.addWidget(self.plot)
        self.legend = []
        legend = QGridLayout()
        for index, (_, label, color) in enumerate(series):
            item = QLabel(label + '：不可用')
            item.setStyleSheet('color:' + color)
            item.setWordWrap(True)
            legend.addWidget(item, index//2, index%2)
            self.legend.append(item)
        layout.addLayout(legend)
        self.age = QLabel('尚无采样；时间轴最多保留十分钟')
        self.age.setWordWrap(True)
        self.age.setObjectName('muted')
        layout.addWidget(self.age)

    def append(self, sample):
        now = time.monotonic()
        if self.started_at is None:
            self.started_at = now
        self.points.append((now, sample))
        while self.points and now - self.points[0][0] > 600:
            self.points.popleft()
        for item, (key, label, _) in zip(self.legend, self.series):
            item.setText(label + '：' + number(sample.get(key)))
        elapsed = now-self.points[0][0]
        self.age.setText(f'累计监测 {now-self.started_at:.0f} 秒 · 图示最近 {max(30, min(600, elapsed)):.0f} 秒')
        self.plot.update()


class SummaryCard(QFrame):
    def __init__(self, title, percent=False):
        super().__init__()
        self.setObjectName('metric')
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)
        label = QLabel(title)
        label.setObjectName('muted')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.value = QLabel('不可用')
        self.value.setStyleSheet('font-size:18px;font-weight:600;color:#71dfec')
        self.value.setWordWrap(True)
        layout.addWidget(self.value)
        self.detail = QLabel('等待采样')
        self.detail.setObjectName('muted')
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.detail)
        self.bar = QProgressBar() if percent else None
        if self.bar:
            self.bar.setRange(0, 1000)
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(5)
            layout.addWidget(self.bar)
            self.bar.hide()

    def show_value(self, value, suffix, detail, stale=False, digits=1):
        self.value.setText('已过期' if stale else number(value, suffix, digits))
        self.detail.setText(detail)
        if self.bar:
            self.bar.setVisible(value is not None and not stale)
            if value is not None:
                self.bar.setValue(round(max(0, min(100, value))*10))


def update_overview(window, row):
    stale = row.get('board_stale', True)
    cards = window.performance_cards
    cards['stream'].show_value(row.get('pc_session_mbps'), ' Mbit/s',
        '占链路 ' + number(row.get('pc_session_link_percent'), '%', 2) + '\n仅当前电脑订阅', stale)
    cards['nic'].show_value(row.get('nic_tx_percent'), '%',
        (row.get('nic_name') or '网口') + ' · ' + number(row.get('nic_tx_mbps'), ' Mbit/s')
        + '\n链路 ' + number(row.get('link_mbps'), ' Mbit/s', 0), stale, 2)
    for host, title in [('board', '开发板'), ('pc', '电脑')]:
        cards[host+'_cpu'].show_value(row.get(host+'_cpu_percent'), '%',
            '整机占用 · 全部核心', stale if host == 'board' else False)
        cards[host+'_ram'].show_value(row.get(host+'_memory_percent'), '%',
            number(row.get(host+'_memory_used_gib')) + ' / ' + number(row.get(host+'_memory_total_gib'), ' GiB'),
            stale if host == 'board' else False)
    for key, field in [('decode', 'pc_decode_fps'), ('paint', 'qt_paint_fps')]:
        cards[key].show_value(row.get(field), ' fps',
            (row.get('pc_decode_size') if key == 'decode' else row.get('preview_size')) or '等待画面',
            row.get('video_age_s') is None or row.get('video_age_s', 0) > 4)
    window.capture_summary.setText('采集 ' + number(row.get('capture_fps'), ' fps')
        + ' → 编码 ' + number(row.get('encode_fps'), ' fps')
        + '\n板端硬解 ' + number(row.get('board_decode_fps'), ' fps')
        + ' · 板温 ' + number(row.get('board_temperature_c'), '℃')
        + '\n采集序号缺口：本次新增 ' + number(row.get('capture_new_gaps'), digits=0)
        + ' / 累计 ' + number(row.get('capture_gaps'), digits=0))
    window.capture_summary.setToolTip('本次新增以本次连接首次有效采样为基线；断线或采集进程更换后重新建立基线。累计值保留启动阶段缺口，不会清零伪装。')


def build_performance(window, layout):
    window.performance_note = QLabel('每秒采样 · 最近十分钟 · 不可用值不绘制曲线')
    window.performance_note.setWordWrap(True)
    window.performance_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout.addWidget(window.performance_note)
    grid = QGridLayout()
    window.performance_cards = {}
    for i, (key, title, percent) in enumerate([
        ('stream', '本订阅流速', False), ('nic', '网口总 TX 占用', True),
        ('board_cpu', '板端 CPU', True), ('pc_cpu', '电脑 CPU', True),
        ('board_ram', '板端内存', True), ('pc_ram', '电脑内存', True),
        ('decode', '电脑完整解码', False), ('paint', '实际画面绘制', False)]):
        card = SummaryCard(title, percent)
        window.performance_cards[key] = card
        grid.addWidget(card, i//2, i%2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    layout.addLayout(grid)
    window.capture_summary = QLabel('等待采集与编码统计')
    window.capture_summary.setWordWrap(True)
    layout.addWidget(window.capture_summary)
    toggle = QPushButton('展开趋势图')
    toggle.setCheckable(True)
    layout.addWidget(toggle)
    trends = QWidget()
    charts = QVBoxLayout(trends)
    charts.setContentsMargins(0, 0, 0, 0)
    window.fps_trend = Trend([('capture_fps', '采集', '#6de0b7'), ('encode_fps', '编码', '#e6b45f'),
        ('pc_decode_fps', '电脑解码', '#72b1ff'), ('qt_paint_fps', 'Qt 绘制', '#e48fe7')], 'fps')
    window.flow_trend = Trend([('rtsp_mbps', 'RTSP', '#6de0b7'), ('pc_session_mbps', '本订阅', '#72b1ff'),
                              ('nic_tx_mbps', '网口TX', '#e6b45f')], 'Mbit/s')
    charts.addWidget(window.fps_trend)
    charts.addWidget(window.flow_trend)
    layout.addWidget(trends)
    trends.hide()
    toggle.toggled.connect(trends.setVisible)
    toggle.toggled.connect(lambda opened: toggle.setText('收起趋势图' if opened else '展开趋势图'))
    window.trend_toggle = toggle
    details_toggle = QPushButton('展开详细指标与 CSV 路径')
    details_toggle.setCheckable(True)
    layout.addWidget(details_toggle)
    window.performance_detail = WrappingDetails()
    layout.addWidget(window.performance_detail)
    window.performance_detail.hide()
    details_toggle.toggled.connect(window.performance_detail.setVisible)
    details_toggle.toggled.connect(lambda opened: details_toggle.setText('收起详细指标与 CSV 路径' if opened else '展开详细指标与 CSV 路径'))
    window.details_toggle = details_toggle
    for title, callback in [('选择 CSV 保存目录', window.choose_performance_folder),
                            ('导出本次 CSV', window.export_performance),
                            ('打开 CSV 目录', window.open_performance_folder)]:
        button = QPushButton(title)
        button.clicked.connect(callback)
        layout.addWidget(button)
    layout.addStretch()
