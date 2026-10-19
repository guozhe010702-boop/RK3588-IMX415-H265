"""Desktop coordinator: translate UI events and worker results into visible state.

Layout lives in layout.py. SSH, decoding and SFTP are separate workers.
The board's status response is authoritative for camera/recording lifecycle.
"""

from datetime import datetime
from pathlib import Path
import time
import shutil
import keyring
from PySide6.QtCore import Qt, QTimer, QUrl, QEvent
from PySide6.QtGui import QDesktopServices, QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
    QDialog,
)
from .core import (
    Connection,
    DEFAULT_CONFIG,
    load_preferences,
    save_preferences,
    controls,
    explain_error,
    data_root,
    PREVIEW_PRESETS,
    save_preview_quality,
    PERFORMANCE_CONFIG,
    four_k60_note,
)
from .ssh import SSHWorker, trust_host
from .video import VideoWorker
from .files import FileWorker
from .widgets import STYLE
from .layout import build_ui, button
from .playback import LocalVideoDialog
from .telemetry import PerformanceWorker
from .performance import number


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVM3588 相机控制台")
        self.setMinimumSize(960, 600)
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self.resize(max(960, min(1420, available.width() - 24)) if available else 1420,
                    max(600, min(900, available.height() - 40)) if available else 900)
        self.setStyleSheet(STYLE)
        self.connection, self.download_dir, auto = load_preferences()
        self.board = {}
        self.ssh_connected = False
        self.operation_busy = False
        self.file_busy = False
        self.password = ""
        self.error_until = 0
        self.closing = False
        self.want_board = False
        self.pending_logs = []
        self.displayed_frames = 0
        self.rate_sample = (time.monotonic(), 0, 0)
        self.log_timer = QTimer(self)
        self.log_timer.setInterval(200)
        self.log_timer.timeout.connect(self.flush_logs)
        self.log_timer.start()
        self.pending_stop_recording = False
        self.rows = []
        self.local_files = {}
        self.last_history = None
        self.fullscreen = None
        self.file_viewers = []
        self.event_log = []
        self.video_state = "未播放"
        self.ssh = SSHWorker()
        self.video = VideoWorker()
        self.files = FileWorker()
        build_ui(self, auto)
        self.performance = PerformanceWorker(self.video, self.canvas)
        self.performance.sample.connect(self.on_performance)
        self.performance.failure.connect(lambda text: self.add_log('系统', '性能 CSV：' + text))
        self.latest_performance = {}
        self.performance.start()
        self.restore_saved_credential()
        self.connect_signals()
        self.ssh.start()
        self.video.start()
        self.files.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(8)
        self.timer.timeout.connect(self.render_frame)
        self.timer.start()
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.clock.timeout.connect(self.update_clock)
        self.clock.start()
        self.update_controls()
        self.add_log("系统", "控制台已就绪。先连接开发板，已有直播将自动显示。")

    def restore_saved_credential(self):
        if self.connection.remember:
            try:
                self.secret.setText(
                    keyring.get_password("EVM3588CameraConsole", self.connection.credential_id)
                    or ""
                )
            except Exception as error:
                self.add_log("连接", str(error))

    def connect_signals(self):
        self.ssh.connected.connect(self.on_connection)
        self.ssh.status.connect(self.on_status)
        self.ssh.result.connect(self.on_result)
        self.ssh.failure.connect(self.on_failure)
        self.ssh.host_key.connect(self.on_host_key)
        self.ssh.busy.connect(self.on_busy)
        self.video.state.connect(self.on_video_state)
        self.video.log.connect(lambda text: self.add_log("播放", text))
        self.files.listing.connect(self.on_listing)
        self.files.progress.connect(self.on_progress)
        self.files.completed.connect(self.on_download)
        self.files.failure.connect(lambda text: self.on_failure("download", text))
        self.files.busy.connect(self.on_file_busy)

    def select_page(self, index):
        self.side_panel.setFixedWidth(500 if index == 4 else 350)
        self.pages.setCurrentIndex(index)
        for i, item in enumerate(self.tab_buttons):
            item.setChecked(i == index)

    def choose_key(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择 SSH 私钥")
        if file:
            self.key_file.setText(file)
            self.auth.setCurrentIndex(1)

    def connect_board(self):
        try:
            self.connection = Connection(
                self.host.text().strip(),
                self.port.value(),
                self.username.text().strip(),
                "key" if self.auth.currentIndex() else "password",
                self.key_file.text().strip(),
                self.remember.isChecked(),
            ).validate()
            self.password = self.secret.text()
            if self.connection.remember:
                keyring.set_password(
                    "EVM3588CameraConsole", self.connection.credential_id, self.password
                )
            else:
                try:
                    keyring.delete_password("EVM3588CameraConsole", self.connection.credential_id)
                except keyring.errors.PasswordDeleteError:
                    pass
            self.save_settings()
            self.files.configure(self.connection, self.password)
            self.want_board = True
            self.have_config = False
            self.ssh.submit("connect", (self.connection, self.password))
            self.message.setText("正在连接 SSH 并查询板端状态…")
        except Exception as error:
            self.on_failure("connect", str(error))

    def disconnect_board(self):
        self.performance.set_connected(False)
        self.want_board = False
        self.ssh.submit("disconnect")
        self.video.pause()
        self.files.disconnect()
        self.password = ""
        self.board = {}
        self.ssh_connected = False
        self.update_controls()
        self.badges["SSH"].set_state(False, "未连接")
        self.canvas.set_message("控制与电脑预览已断开；板端任务继续运行", clear=True)

    def on_host_key(self, details):
        reply = QMessageBox.question(
            self,
            "确认开发板身份",
            f"首次连接 {details['host']}\n\n主机指纹：\n{details['fingerprint']}\n\n确认这是你的开发板后保存该指纹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                trust_host(details)
                self.ssh.submit("connect", (self.connection, self.password))
            except Exception as error:
                self.on_failure("connect", str(error))
        else:
            self.message.setText("尚未信任主机，连接已取消。")

    def on_connection(self, connected, message):
        if self.closing or (connected and not self.want_board):
            return
        self.ssh_connected = connected
        self.performance.set_connected(connected)
        self.badges["SSH"].set_state(connected, "已连接" if connected else "未连接")
        self.connection_note.setText(message)
        self.add_log("连接", message)
        self.update_controls()
        if connected:
            self.files.configure(self.connection, self.password)
            self.files.submit("list")

    def on_busy(self, value):
        self.operation_busy = value
        self.update_controls()

    def on_file_busy(self, value):
        self.file_busy = value
        self.update_controls()

    def update_controls(self):
        state = controls(self.board, self.ssh_connected, self.operation_busy)
        for action, item in self.action_buttons.items():
            item.setEnabled(state[action])
        self.apply_button.setEnabled(state["apply"])
        self.hdmi_button.setEnabled(state["hdmi"])
        self.refresh_files.setEnabled(self.ssh_connected and not self.file_busy)
        self.download_button.setEnabled(self.ssh_connected and not self.file_busy)
        self.hdmi_button.setText("HDMI 关闭" if self.board.get("previewRunning") else "HDMI 开启")

    def action(self, action):
        if self.operation_busy or not self.ssh_connected:
            return
        if action == "stop" and self.board.get("recording"):
            if (
                QMessageBox.question(self, "停止直播", "停止直播会先结束正在进行的录像。继续？")
                != QMessageBox.StandardButton.Yes
            ):
                return
        if action == "stop":
            self.pending_stop_recording = bool(self.board.get("recording"))
        self.on_busy(True)
        self.ssh.submit(action)
        self.message.setText(
            {
                "start": "正在启动直播…",
                "stop": "正在停止直播并释放摄像头…",
                "snapshot": "正在截图…",
                "record-start": "正在开始录像…",
                "record-stop": "正在结束录像并验证 MP4…",
            }.get(action, "正在执行操作…")
        )

    def toggle_hdmi(self):
        self.action("preview-stop" if self.board.get("previewRunning") else "preview-start")

    def requested_config(self):
        return {
            "device": self.device.text().strip(),
            "codec": "h264" if self.codec.currentIndex() else "h265",
            "width": self.width.value(),
            "height": self.height.value(),
            "fps": self.fps.value(),
            "bitrate": round(self.bitrate.value() * 1000000),
            "gop": self.gop.value(),
        }

    def apply_config(self):
        config = self.requested_config()
        if config["width"] % 8 or config["height"] % 8:
            self.on_failure("start", "当前 ISP 尺寸步长为 8，请使用宽高均为 8 的倍数的尺寸")
            return
        if self.board.get("recording"):
            self.on_failure("start", "Stop and finalize recording")
            return
        self.on_busy(True)
        self.ssh.submit("start", config)
        self.message.setText("正在应用参数，视频会短暂重连…")

    def fill_config(self):
        config = self.board.get("config", DEFAULT_CONFIG)
        self.codec.setCurrentIndex(config.get("codec") == "h264")
        self.width.setValue(config.get("width", 1920))
        self.height.setValue(config.get("height", 1080))
        self.fps.setValue(config.get("fps", 30))
        self.bitrate.setValue(config.get("bitrate", 2500000) / 1000000)
        self.gop.setValue(config.get("gop", 30))
        self.device.setText(config.get("device", "/dev/video44"))

    def fill_performance_preset(self):
        if self.board.get('recording'):
            self.on_failure('start', 'Stop and finalize recording')
            return
        c = PERFORMANCE_CONFIG
        self.codec.setCurrentIndex(0)
        self.width.setValue(c['width'])
        self.height.setValue(c['height'])
        self.fps.setValue(c['fps'])
        self.bitrate.setValue(c['bitrate'] / 1e6)
        self.gop.setValue(c['gop'])
        self.preview_quality.setCurrentText('性能 60 fps')
        self.message.setText('已填入 4K60 性能预设，尚未应用。\n' + four_k60_note(getattr(self, 'camera_capabilities', {})))

    def on_status(self, status):
        if self.closing or not self.want_board:
            return
        previous = self.board
        self.board = status
        self.performance.update_board(status, self.ssh_connected)
        ready = status.get("state") == "running"
        config = status.get("config", {})
        self.badges["VPU"].set_state(
            bool(status.get("vpuDeviceOpen")), "硬编" if status.get("vpuDeviceOpen") else "未运行"
        )
        self.badges["HDMI"].set_state(
            bool(status.get("previewRunning")),
            "已开启" if status.get("previewRunning") else "已关闭",
        )
        self.badges["录像"].set_state(
            bool(status.get("recording")), "录制中" if status.get("recording") else "未录像"
        )
        actual = status.get("actualCapture") or {}
        width = actual.get("width", config.get("width", 1920))
        height = actual.get("height", config.get("height", 1080))
        self.metrics["size"].value.setText(f"{width}×{height}")
        self.metrics["bitrate"].value.setToolTip(f"配置目标码率 {config.get('bitrate',0)/1e6:g} Mbit/s；卡片显示实测 RTSP 流速")
        self.metrics["disk"].value.setText(f"{status.get('freeBytes',0)/1024**3:.1f} GiB")
        self.actual_text.setText(
            f"运行值：{config.get('codec','—').upper()} · {width}×{height}\n{config.get('fps','—')} fps · {config.get('bitrate',0)/1000000:g} Mbit/s · GOP {config.get('gop','—')}\n实际编码器：{status.get('encoder','—')}\n{'采集尺寸已确认' if actual else '采集尺寸等待板端报告'}"
        )
        self.stream_text.setText(f"{config.get('codec','—').upper()} · {self.connection.rtsp_url}")
        self.footer.setText(
            f"  帧进度 {status.get('frame',0):,}   ·   丢帧 {status.get('droppedFrames') or 0}   ·   补帧 {status.get('duplicateFrames') or 0}   ·   订阅者 {status.get('readers',0)}   ·   状态更新时间 {datetime.now():%H:%M:%S}"
        )
        if not getattr(self, "have_config", False):
            self.fill_config()
            self.have_config = True
        if ready:
            token = (status.get("capturePid"), width, height, config.get("codec"))
            self.video.configure(self.connection.rtsp_url, width, height, token)
        elif previous.get("state") == "running":
            self.video.pause()
            self.canvas.set_message("直播已停止或正在恢复", clear=True)
        error = status.get("lastError")
        if error and error != self.last_history:
            self.last_history = error
            self.add_log("编码", "历史事件：" + str(error.get("message", error)))
        if ready and not self.operation_busy and time.monotonic() >= self.error_until:
            self.message.setText("直播正常；可以截图、录像或修改编码参数。")
        elif status.get('state') == 'stopped' and not self.operation_busy and time.monotonic() >= self.error_until:
            self.message.setText('板端控制服务未运行；SSH 已连接，可点击启动直播。' if status.get('serviceRunning') is False
                                 else '直播未启动；可以设置参数并启动直播。')
        self.update_controls()
        self.update_clock()

    def on_result(self, action, response):
        if getattr(self, "closing", False) or not getattr(self, "want_board", True):
            return
        if not response.get("ok"):
            recovery = response.get("result", {}).get("recovery", {})
            note = "（原直播已恢复）" if recovery.get("restored") else ""
            self.on_failure(action, str(response.get("error")) + note)
            return
        result = response.get("result", {})
        if action == "check":
            self.camera_capabilities = result
            item = self.codec.model().item(1)
            item.setEnabled("h264_rkmpp" in result.get("encoders", []))
            self.add_log("系统", "板端硬编能力：" + ", ".join(result.get("encoders", [])))
            self.capability_note.setText(four_k60_note(result))
            self.fps.setMaximum(60)
        elif action == "snapshot":
            self.files.submit("download", (result["file"], self.download_path.text()))
            self.files.submit("list")
        elif action in ("record-stop", "stop"):
            if action == "stop" and result.get("recordingResult", {}).get("error"):
                self.on_failure(
                    "record-stop",
                    "直播已停止，但录像封口失败：" + str(result["recordingResult"]["error"]),
                )
                self.files.submit("list")
                return
            recording = result.get("lastRecording") or result.get("recordingResult", {}).get(
                "lastRecording"
            )
            if (
                recording
                and self.auto_download.isChecked()
                and (action == "record-stop" or self.pending_stop_recording)
            ):
                self.files.submit("download", (recording["file"], self.download_path.text()))
            self.pending_stop_recording = False
            self.files.submit("list")
        elif action == "logs":
            for key, lines in result.items():
                for line in lines:
                    self.add_log(
                        {"capture": "编码", "recording": "录像", "preview": "播放"}.get(
                            key, "控制"
                        ),
                        line,
                    )
        if action != "check":
            self.add_log("控制", action + " 已完成")

    def on_failure(self, action, text):
        category = (
            "文件"
            if action == "download"
            else ("连接" if action in ("connect", "status") else "控制")
        )
        self.add_log(category, text)
        self.message.setText(explain_error(text))
        self.message.setToolTip(text)
        self.error_until = time.monotonic() + 8

    def on_video_state(self, text):
        self.video_state = text
        self.badges["视频"].set_state(text == "实时画面", text)
        if text != "实时画面":
            self.canvas.set_message(text)

    def render_frame(self):
        frame = self.video.take_frame()
        if frame:
            self.canvas.set_frame(frame[0], frame[1], frame[2])
            self.displayed_frames += 1

    def change_preview_quality(self, quality):
        save_preview_quality(quality)
        self.video.set_quality(*PREVIEW_PRESETS[quality])
        self.reconnect_video()
        self.add_log("播放", f"电脑预览切换为{quality}；板端直播和录像保持原参数。")

    def reconnect_video(self):
        self.video.pause()
        if self.board.get("state") == "running":
            config = self.board["config"]
            self.video.configure(
                self.connection.rtsp_url,
                config["width"],
                config["height"],
                (self.board.get("capturePid"), config["width"], config["height"], config["codec"]),
            )

    def enter_fullscreen(self):
        if self.fullscreen:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("实时视频 · Esc 返回")
        layout = QVBoxLayout(dialog)
        layout.addWidget(self.canvas)
        layout.addWidget(button("返回控制台", dialog.reject))
        dialog.finished.connect(self.leave_fullscreen)
        self.fullscreen = dialog
        dialog.showFullScreen()

    def leave_fullscreen(self):
        if self.fullscreen:
            self.video_holder.addWidget(self.canvas)
            self.fullscreen.deleteLater()
            self.fullscreen = None

    def update_clock(self):
        started = self.board.get("recordingStartedAt")
        if started:
            try:
                elapsed = max(0, int(time.time() - datetime.fromisoformat(started).timestamp()))
                self.record_clock.setText(
                    f"● 录像中  {elapsed//3600:02}:{elapsed//60%60:02}:{elapsed%60:02}"
                )
            except ValueError:
                self.record_clock.setText("录像中")
        else:
            self.record_clock.setText("未录像 · 录像保存到板端，结束后可下载")

    def on_performance(self, row):
        if self.closing:
            return
        self.latest_performance = row
        self.fps_trend.append(row)
        self.flow_trend.append(row)
        self.metrics['fps'].value.setText(number(row.get('encode_fps'), ' fps'))
        self.metrics['bitrate'].value.setText(number(row.get('rtsp_mbps'), ' M'))
        self.preview_stats.setText('电脑解码 ' + number(row.get('pc_decode_fps'), ' fps')
            + ' · Qt 绘制 ' + number(row.get('qt_paint_fps'), ' fps')
            + ' · 订阅流速 ' + number(row.get('pc_session_mbps'), ' Mbit/s')
            + ' · ' + (row.get('bottleneck') or '每秒差分采样'))
        self.performance_note.setText(('已过期' if row['board_stale'] else '指标正常')
            + ' · 板端数据年龄 ' + number(row.get('board_age_s'), 's')
            + '\n' + (row.get('bottleneck') or '十分钟趋势；进程 CPU 以一个逻辑核为 100%'))
        pairs = [
            ('采集 / 传感器', number(row.get('capture_fps'), ' fps') + ' / ' + number(row.get('sensor_fps'), ' fps')),
            ('驱动序号缺口 / 错帧', number(row.get('capture_gaps'), digits=0) + ' / ' + number(row.get('capture_errors'), digits=0)),
            ('板端硬解', (row.get('board_decode_size') or '不可用') + ' · ' + number(row.get('board_decode_fps'), ' fps')),
            ('解码器 / VPU 设备', (row.get('board_decoder_name') or '不可用') + ' / ' + ('已打开' if row.get('board_decoder_vpu_open') else '未确认')),
            ('板解状态 / 错误', ('运行' if row.get('board_decode_running') else '未运行') + ' / ' + (row.get('board_decode_error') or '无已报告错误')),
            ('HDMI 输入 / 显示模式', (row.get('hdmi_size') or '不可用') + ' / ' + (row.get('monitor_mode') or '不可用')),
            ('电脑解码 / 预览', (row.get('pc_decode_size') or '不可用') + ' / ' + (row.get('preview_size') or '不可用')),
            ('预览丢弃 / 重连', str(row['preview_discarded']) + ' / ' + str(row['reconnects'])),
            ('电脑解码错误日志条数', number(row.get('pc_decode_errors'), digits=0)),
            ('目标 / 实测 RTSP', number(row.get('target_mbps')) + ' / ' + number(row.get('rtsp_mbps'), ' Mbit/s')),
            ('网口 TX / RX', (row.get('nic_name') or '不可用') + ' · ' + number(row.get('nic_tx_mbps')) + ' / ' + number(row.get('nic_rx_mbps'), ' Mbit/s')),
            ('链路 / TX 占用', number(row.get('link_mbps'), ' Mbit/s') + ' / ' + number(row.get('nic_tx_percent'), '%')),
            ('板端 / 电脑 CPU', number(row.get('board_cpu_percent'), '%') + ' / ' + number(row.get('pc_cpu_percent'), '%')),
            ('编码 / 板解内存', number(row.get('board_encoder_rss_mib')) + ' / ' + number(row.get('board_decoder_rss_mib'), ' MiB')),
            ('编码 / 板解 CPU', number(row.get('board_encoder_cpu_percent'), '%') + ' / ' + number(row.get('board_decoder_cpu_percent'), '%')),
            ('电脑解码 / 界面内存', number(row.get('pc_decoder_rss_mib')) + ' / ' + number(row.get('gui_rss_mib'), ' MiB')),
            ('电脑解码 / 界面 CPU', number(row.get('pc_decoder_cpu_percent'), '%') + ' / ' + number(row.get('gui_cpu_percent'), '%')),
            ('板端温度', number(row.get('board_temperature_c'), '℃')),
            ('VPU 频率 Hz', row.get('vpu_frequencies') or '不可用'),
            ('首帧等待 / 帧年龄', number(row.get('first_frame_s'), 's') + ' / ' + number(row.get('video_age_s'), 's')),
        ]
        self.performance_detail.setText('\n'.join(title + '：' + value for title, value in pairs)
            + '\nCSV：' + (row.get('csv_path') or '等待写入')
            + ('\n保存失败：' + row['csv_error'] if row.get('csv_error') else ''))

    def choose_performance_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择性能 CSV 保存目录', str(self.performance.folder))
        if folder:
            self.performance.set_folder(folder)

    def open_performance_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.performance.folder)))

    def export_performance(self):
        source = self.latest_performance.get('csv_path')
        if not source:
            self.message.setText('CSV 尚未生成')
            return
        target, _ = QFileDialog.getSaveFileName(self, '导出本次性能 CSV', Path(source).name, 'CSV (*.csv)')
        if target and Path(target).resolve() != Path(source).resolve():
            try:
                shutil.copyfile(source, target)
                self.message.setText('已导出截至当前采样的 CSV：' + target)
            except OSError as error:
                self.on_failure('export', str(error))

    def on_listing(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, text in enumerate(
                (
                    row["name"],
                    f"{row['bytes']/1024**2:.1f} MB",
                    "完成" if row["complete"] else "写入中",
                )
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(row["path"])
                self.table.setItem(index, column, item)

    def download_selected(self):
        index = self.table.currentRow()
        if index < 0:
            self.download_note.setText("请先选择要下载的文件。")
            return
        row = self.rows[index]
        if not row["complete"]:
            self.download_note.setText("录像仍在写入，请停止录像并等待封口。")
            return
        self.save_settings()
        self.files.submit("download", (row["path"], self.download_path.text()))

    def on_progress(self, remote, done, total):
        self.progress.setValue(int(done / max(1, total) * 100))
        self.download_note.setText(f"正在下载：{done/1024**2:.1f} / {total/1024**2:.1f} MB")

    def on_download(self, remote, local):
        self.last_local = local
        self.local_files[remote] = local
        self.progress.setValue(100)
        self.download_note.setText("SHA-256 校验通过，已保存：" + local)
        self.add_log("文件", "下载与 SHA-256 校验完成：" + local)
        if local.lower().endswith(".jpg"):
            self.thumbnail.setPixmap(
                QPixmap(local).scaled(
                    300,
                    130,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def choose_download(self):
        folder = QFileDialog.getExistingDirectory(
            self, "选择电脑保存目录", self.download_path.text()
        )
        if folder:
            self.download_path.setText(folder)
            self.save_settings()

    def open_download(self):
        folder = Path(self.download_path.text())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_last_file(self):
        if self.last_local:
            if self.last_local.lower().endswith(".mp4"):
                viewer = LocalVideoDialog(self.last_local, self)
                self.file_viewers.append(viewer)
                viewer.show()
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_local))

    def save_settings(self):
        save_preferences(self.connection, self.download_path.text(), self.auto_download.isChecked())

    def add_log(self, category, text):
        line = f"[{datetime.now():%H:%M:%S}] [{category}] {text}"
        self.event_log.append((category, line))
        self.event_log = self.event_log[-1000:]
        self.pending_logs.append((category, line))
        self.pending_logs = self.pending_logs[-1000:]

    def flush_logs(self):
        if not self.pending_logs:
            return
        pending, self.pending_logs = self.pending_logs, []
        try:
            path = data_root() / "console.log"
            if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
                path.replace(data_root() / "console.previous.log")
            with path.open("a", encoding="utf-8") as file:
                file.write("\n".join(line for _, line in pending) + "\n")
        except OSError as error:
            self.message.setToolTip("本地日志写入失败：" + str(error))
        category = self.log_filter.currentText()
        lines = [line for group, line in pending if category == "全部" or category == group]
        if lines:
            bar = self.log_view.verticalScrollBar()
            follow = bar.value() >= bar.maximum() - 2
            position = bar.value()
            self.log_view.appendPlainText("\n".join(lines))
            bar.setValue(bar.maximum() if follow else position)

    def render_logs(self):
        self.flush_logs()
        category = self.log_filter.currentText()
        lines = [line for group, line in self.event_log if category == "全部" or category == group]
        self.log_view.setPlainText("\n".join(lines))
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def copy_logs(self):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.log_view.toPlainText())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'performance'):
            self.performance.set_window_minimized(self.isMinimized())

    def closeEvent(self, event):
        if not self.closing:
            self.closing = True
            self.timer.stop()
            self.clock.stop()
            self.log_timer.stop()
            self.save_settings()
            self.flush_logs()
            self.centralWidget().setEnabled(False)
            self.message.setText("正在退出电脑连接与预览；板端任务继续运行…")
            for viewer in list(self.file_viewers):
                viewer.close()
            self.ssh.shutdown()
            self.video.shutdown()
            self.files.shutdown()
            self.performance.shutdown()
            self.close_timer = QTimer(self)
            self.close_timer.setInterval(100)
            self.close_timer.timeout.connect(self.finish_close)
            self.close_timer.start()
        if (
            any(worker.isRunning() for worker in (self.ssh, self.video, self.files, self.performance))
            or self.file_viewers
        ):
            event.ignore()
            return
        self.close_timer.stop()
        self.flush_logs()
        self.secret.clear()
        self.password = ""
        event.accept()

    def finish_close(self):
        if (
            not any(worker.isRunning() for worker in (self.ssh, self.video, self.files, self.performance))
            and not self.file_viewers
        ):
            self.close()
