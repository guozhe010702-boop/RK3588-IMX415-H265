"""Build widgets and bind callbacks; contains no SSH or media lifecycle code.

The MainWindow owns the created widget references. Page builders only assemble
the view; callbacks are handled by window.py and dispatched to background workers.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QFrame,
    QStackedWidget,
    QPlainTextEdit,
    QTableWidget,
    QHeaderView,
    QProgressBar,
    QScrollArea,
)
from .core import PREVIEW_PRESETS, load_preview_quality, data_root
from .widgets import Badge, Metric, VideoCanvas
from .performance import build_performance


def button(text, callback, name=""):
    value = QPushButton(text)
    value.setObjectName(name)
    value.clicked.connect(callback)
    return value


def build_ui(window, auto):
    root = QWidget()
    window.setCentralWidget(root)
    outer = QVBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    header = QWidget()
    header.setObjectName("header")
    head = QHBoxLayout(header)
    head.setContentsMargins(24, 18, 24, 18)
    brand = QVBoxLayout()
    title = QLabel("EVM3588  /  相机控制台")
    title.setObjectName("title")
    brand.addWidget(title)
    subtitle = QLabel("IMX415 · RK3588 VPU · 实时预览与录像")
    subtitle.setObjectName("subtitle")
    brand.addWidget(subtitle)
    head.addLayout(brand)
    head.addStretch()
    window.badges = {name: Badge(name) for name in ("SSH", "视频", "VPU", "HDMI", "录像")}
    for badge in window.badges.values():
        head.addWidget(badge)
    outer.addWidget(header)
    body = QHBoxLayout()
    body.setContentsMargins(22, 20, 22, 16)
    body.setSpacing(20)
    outer.addLayout(body, 1)
    left = QVBoxLayout()
    body.addLayout(left, 1)
    caption = QHBoxLayout()
    label = QLabel("实时画面")
    label.setObjectName("section")
    caption.addWidget(label)
    window.stream_text = QLabel("等待连接")
    window.stream_text.setObjectName("muted")
    caption.addWidget(window.stream_text)
    caption.addStretch()
    window.preview_quality = QComboBox()
    window.preview_quality.addItems(list(PREVIEW_PRESETS))
    window.preview_quality.setCurrentText(load_preview_quality())
    window.preview_quality.setToolTip("仅改变电脑预览尺寸与帧率；板端编码、HDMI 和录像参数不变")
    window.preview_quality.currentTextChanged.connect(window.change_preview_quality)
    caption.addWidget(window.preview_quality)
    window.video.set_quality(*PREVIEW_PRESETS[window.preview_quality.currentText()])
    caption.addWidget(button("重新播放", window.reconnect_video))
    caption.addWidget(button("全屏", window.enter_fullscreen))
    left.addLayout(caption)
    window.video_holder = QVBoxLayout()
    window.video_holder.setContentsMargins(0, 0, 0, 0)
    video_frame = QFrame()
    video_frame.setObjectName("panel")
    video_frame.setLayout(window.video_holder)
    window.canvas = VideoCanvas()
    window.video_holder.addWidget(window.canvas)
    left.addWidget(video_frame, 1)
    window.message = QLabel("先在右侧填写连接信息；已有直播会自动接入。")
    window.message.setWordWrap(True)
    window.message.setObjectName("muted")
    left.addWidget(window.message)
    metrics = QHBoxLayout()
    window.metrics = {}
    for key, title in [
        ("fps", "编码帧率"),
        ("size", "采集尺寸"),
        ("bitrate", "实测 RTSP Mbit/s"),
        ("disk", "板端剩余空间"),
    ]:
        window.metrics[key] = Metric(title)
        metrics.addWidget(window.metrics[key])
    left.addLayout(metrics)
    window.preview_stats = QLabel("电脑预览：等待画面")
    window.preview_stats.setObjectName("muted")
    left.addWidget(window.preview_stats)
    toolbar = QHBoxLayout()
    window.action_buttons = {}
    for action, text, name in [
        ("start", "▶ 启动直播", "primary"),
        ("stop", "■ 停止直播", ""),
        ("snapshot", "截图", ""),
        ("record-start", "● 开始录像", "primary"),
        ("record-stop", "■ 停止录像", "danger"),
    ]:
        item = button(text, lambda checked=False, a=action: window.action(a), name)
        window.action_buttons[action] = item
        toolbar.addWidget(item)
    left.addLayout(toolbar)
    bottom = QHBoxLayout()
    window.record_clock = QLabel("未录像")
    window.record_clock.setObjectName("muted")
    bottom.addWidget(window.record_clock)
    bottom.addStretch()
    window.hdmi_button = button("HDMI 开启", window.toggle_hdmi)
    bottom.addWidget(window.hdmi_button)
    left.addLayout(bottom)
    panel = QFrame()
    window.side_panel = panel
    panel.setObjectName("panel")
    panel.setFixedWidth(350)
    right = QVBoxLayout(panel)
    right.setContentsMargins(14, 16, 14, 16)
    tabs = QGridLayout()
    window.pages = QStackedWidget()
    window.tab_buttons = []
    for i, name in enumerate(("设备连接", "编码设置", "媒体文件", "运行日志", "性能监测")):
        item = button(name, lambda checked=False, index=i: window.select_page(index), "tab")
        item.setCheckable(True)
        tabs.addWidget(item, i // 2, i % 2)
        window.tab_buttons.append(item)
    right.addLayout(tabs)
    right.addWidget(window.pages, 1)
    body.addWidget(panel)
    build_connection(window)
    build_encoding(window)
    build_media(window, auto)
    build_logs(window)
    build_performance(window, page(window, '编解码性能'))
    window.select_page(0)
    window.footer = QLabel("  单相机 · RTSP TCP · 关闭软件后板端任务继续运行")
    window.footer.setObjectName("muted")
    window.footer.setContentsMargins(22, 6, 22, 14)
    outer.addWidget(window.footer)


def page(window, title):
    content = QWidget()
    content.setObjectName("page")
    content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 15, 0, 0)
    layout.setSpacing(12)
    label = QLabel(title)
    label.setObjectName("section")
    layout.addWidget(label)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    window.pages.addWidget(scroll)
    return layout


def build_connection(window):
    layout = page(window, "连接你的开发板")
    form = QFormLayout()
    form.setSpacing(10)
    window.host = QLineEdit(window.connection.host)
    window.port = QSpinBox()
    window.port.setRange(1, 65535)
    window.port.setValue(window.connection.port)
    window.username = QLineEdit(window.connection.username)
    window.auth = QComboBox()
    window.auth.addItems(["密码登录", "密钥登录"])
    window.auth.setCurrentIndex(window.connection.auth == "key")
    window.secret = QLineEdit()
    window.secret.setEchoMode(QLineEdit.EchoMode.Password)
    window.secret.setPlaceholderText("SSH 密码 / 私钥口令")
    window.key_file = QLineEdit(window.connection.key_file)
    key_row = QHBoxLayout()
    key_row.addWidget(window.key_file)
    key_row.addWidget(button("选择", window.choose_key))
    for name, widget in [
        ("板子地址", window.host),
        ("SSH 端口", window.port),
        ("用户名", window.username),
        ("认证方式", window.auth),
        ("密码 / 口令", window.secret),
    ]:
        form.addRow(name, widget)
    form.addRow("私钥文件", key_row)
    layout.addLayout(form)
    window.remember = QCheckBox("记住密码（Windows 凭据管理器）")
    window.remember.setChecked(window.connection.remember)
    layout.addWidget(window.remember)
    layout.addWidget(button("连接开发板", window.connect_board, "primary"))
    layout.addWidget(button("断开控制与电脑预览", window.disconnect_board))
    window.connection_note = QLabel(
        "默认 SSH 端口 22。连接后先读取现有任务，已有直播不会重复启动。"
    )
    window.connection_note.setWordWrap(True)
    window.connection_note.setObjectName("muted")
    layout.addWidget(window.connection_note)
    layout.addStretch()


def build_encoding(window):
    layout = page(window, "编码与采集参数")
    window.performance_preset = button('填入 4K60 性能预设', window.fill_performance_preset)
    layout.addWidget(window.performance_preset)
    window.capability_note = QLabel('4K60：等待实际传感器能力检查；预设不代表已支持')
    window.capability_note.setWordWrap(True)
    layout.addWidget(window.capability_note)
    form = QFormLayout()
    form.setSpacing(9)
    window.codec = QComboBox()
    window.codec.addItems(["H.265 / HEVC", "H.264 / AVC"])
    window.width = QSpinBox()
    window.width.setRange(96, 3840)
    window.width.setSingleStep(8)
    window.width.setValue(1920)
    window.height = QSpinBox()
    window.height.setRange(64, 2160)
    window.height.setSingleStep(8)
    window.height.setValue(1080)
    window.fps = QSpinBox()
    window.fps.setRange(1, 60)
    window.fps.setValue(30)
    window.bitrate = QDoubleSpinBox()
    window.bitrate.setRange(0.1, 20)
    window.bitrate.setDecimals(2)
    window.bitrate.setSingleStep(0.5)
    window.bitrate.setSuffix(" Mbit/s")
    window.bitrate.setValue(2.5)
    window.gop = QSpinBox()
    window.gop.setRange(1, 600)
    window.gop.setValue(30)
    window.device = QLineEdit("/dev/video44")
    for name, widget in [
        ("编码格式", window.codec),
        ("宽度", window.width),
        ("高度", window.height),
        ("帧率", window.fps),
        ("CBR 码率", window.bitrate),
        ("GOP 帧数", window.gop),
    ]:
        form.addRow(name, widget)
    layout.addLayout(form)
    window.advanced = QCheckBox("高级：采集节点")
    window.advanced.toggled.connect(window.device.setVisible)
    layout.addWidget(window.advanced)
    layout.addWidget(window.device)
    window.device.hide()
    window.apply_button = button("应用参数并重启直播", window.apply_config, "primary")
    layout.addWidget(window.apply_button)
    layout.addWidget(button("读取当前运行参数", window.fill_config))
    window.actual_text = QLabel("运行值：等待连接")
    window.actual_text.setWordWrap(True)
    layout.addWidget(window.actual_text)
    note = QLabel(
        "尺寸必须满足摄像头能力。修改参数会短暂中断画面；录像中需要先停止录像。失败时尝试恢复原直播。"
    )
    note.setWordWrap(True)
    note.setObjectName("muted")
    layout.addWidget(note)
    layout.addStretch()


def build_media(window, auto):
    layout = page(window, "录像与截图文件")
    window.table = QTableWidget(0, 3)
    window.table.setHorizontalHeaderLabels(["文件名", "大小", "状态"])
    window.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    window.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    window.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    window.table.verticalHeader().hide()
    window.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    window.table.setColumnWidth(1, 67)
    window.table.setColumnWidth(2, 63)
    window.table.setMinimumHeight(220)
    layout.addWidget(window.table)
    row = QHBoxLayout()
    window.refresh_files = button("刷新列表", lambda: window.files.submit("list"))
    window.download_button = button("下载所选", window.download_selected)
    row.addWidget(window.refresh_files)
    row.addWidget(window.download_button)
    layout.addLayout(row)
    window.download_path = QLineEdit(window.download_dir)
    layout.addWidget(QLabel("电脑保存目录"))
    layout.addWidget(window.download_path)
    row = QHBoxLayout()
    row.addWidget(button("选择目录", window.choose_download))
    row.addWidget(button("打开目录", window.open_download))
    layout.addLayout(row)
    window.auto_download = QCheckBox("停止录像后自动下载")
    window.auto_download.setChecked(auto)
    layout.addWidget(window.auto_download)
    window.progress = QProgressBar()
    window.progress.setValue(0)
    layout.addWidget(window.progress)
    window.download_note = QLabel("截图会自动保存到电脑；录像先在板端封口。")
    window.download_note.setWordWrap(True)
    window.download_note.setObjectName("muted")
    layout.addWidget(window.download_note)
    layout.addWidget(button("取消当前下载", window.files.cancel.set))
    window.thumbnail = QLabel("最近截图")
    window.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.thumbnail.setFixedHeight(130)
    window.thumbnail.setObjectName("muted")
    layout.addWidget(window.thumbnail)
    window.open_local = button("打开最近下载的文件", window.open_last_file)
    layout.addWidget(window.open_local)
    layout.addStretch()
    window.last_local = None


def build_logs(window):
    layout = page(window, "运行日志")
    window.log_filter = QComboBox()
    window.log_filter.addItems(["全部", "系统", "连接", "控制", "编码", "录像", "播放", "文件"])
    window.log_filter.currentTextChanged.connect(window.render_logs)
    layout.addWidget(window.log_filter)
    window.log_view = QPlainTextEdit()
    window.log_view.setReadOnly(True)
    window.log_view.setMaximumBlockCount(1000)
    window.log_view.setMinimumHeight(300)
    layout.addWidget(window.log_view, 1)
    layout.addWidget(button("读取板端最近日志", lambda: window.ssh.submit("logs")))
    layout.addWidget(button("复制当前日志", window.copy_logs))
    layout.addWidget(
        button(
            "打开本地日志目录",
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_root()))),
        )
    )
