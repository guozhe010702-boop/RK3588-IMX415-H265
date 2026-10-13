from datetime import datetime
from pathlib import Path
import time
import keyring
from PySide6.QtCore import Qt,QTimer,QUrl
from PySide6.QtGui import QDesktopServices,QPixmap
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QCheckBox,QFileDialog,QMessageBox,QFrame,
    QStackedWidget,QPlainTextEdit,QTableWidget,QTableWidgetItem,QHeaderView,QProgressBar,QDialog,QScrollArea)
from .core import (Connection,DEFAULT_CONFIG,load_preferences,save_preferences,controls,explain_error,data_root,
    PREVIEW_PRESETS,load_preview_quality,save_preview_quality)
from .ssh import SSHWorker,trust_host
from .video import VideoWorker
from .files import FileWorker
from .widgets import STYLE,Badge,Metric,VideoCanvas

def button(text,callback,name=''):
    value=QPushButton(text); value.setObjectName(name); value.clicked.connect(callback); return value

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('EVM3588 相机控制台'); self.resize(1420,900); self.setMinimumSize(1060,660)
        self.setStyleSheet(STYLE); self.connection,self.download_dir,auto=load_preferences()
        self.board={}; self.ssh_connected=False; self.operation_busy=False; self.file_busy=False; self.password=''
        self.error_until=0
        self.closing=False; self.want_board=False; self.pending_logs=[]; self.displayed_frames=0; self.rate_sample=(time.monotonic(),0,0)
        self.log_timer=QTimer(self); self.log_timer.setInterval(200); self.log_timer.timeout.connect(self.flush_logs); self.log_timer.start()
        self.pending_stop_recording=False
        self.rows=[]; self.local_files={}; self.last_history=None; self.fullscreen=None; self.file_viewers=[]; self.event_log=[]; self.video_state='未播放'
        self.ssh=SSHWorker(); self.video=VideoWorker(); self.files=FileWorker()
        self.build_ui(auto); self.connect_signals(); self.ssh.start(); self.video.start(); self.files.start()
        self.timer=QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer); self.timer.setInterval(33); self.timer.timeout.connect(self.render_frame); self.timer.start()
        self.clock=QTimer(self); self.clock.setInterval(1000); self.clock.timeout.connect(self.update_clock); self.clock.start()
        self.update_controls(); self.add_log('系统','控制台已就绪。先连接开发板，已有直播将自动显示。')

    def build_ui(self,auto):
        root=QWidget(); self.setCentralWidget(root); outer=QVBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        header=QWidget(); header.setObjectName('header'); head=QHBoxLayout(header); head.setContentsMargins(24,18,24,18)
        brand=QVBoxLayout(); title=QLabel('EVM3588  /  相机控制台'); title.setObjectName('title'); brand.addWidget(title)
        subtitle=QLabel('IMX415 · RK3588 VPU · 实时预览与录像'); subtitle.setObjectName('subtitle'); brand.addWidget(subtitle); head.addLayout(brand); head.addStretch()
        self.badges={name:Badge(name) for name in ('SSH','视频','VPU','HDMI','录像')}
        for badge in self.badges.values(): head.addWidget(badge)
        outer.addWidget(header)
        body=QHBoxLayout(); body.setContentsMargins(22,20,22,16); body.setSpacing(20); outer.addLayout(body,1)
        left=QVBoxLayout(); body.addLayout(left,1)
        caption=QHBoxLayout(); label=QLabel('实时画面'); label.setObjectName('section'); caption.addWidget(label)
        self.stream_text=QLabel('等待连接'); self.stream_text.setObjectName('muted'); caption.addWidget(self.stream_text); caption.addStretch()
        self.preview_quality=QComboBox(); self.preview_quality.addItems(list(PREVIEW_PRESETS)); self.preview_quality.setCurrentText(load_preview_quality())
        self.preview_quality.setToolTip('仅改变电脑预览尺寸与帧率；板端编码、HDMI 和录像参数不变')
        self.preview_quality.currentTextChanged.connect(self.change_preview_quality); caption.addWidget(self.preview_quality)
        self.video.set_quality(*PREVIEW_PRESETS[self.preview_quality.currentText()])
        caption.addWidget(button('重新播放',self.reconnect_video)); caption.addWidget(button('全屏',self.enter_fullscreen)); left.addLayout(caption)
        self.video_holder=QVBoxLayout(); self.video_holder.setContentsMargins(0,0,0,0)
        video_frame=QFrame(); video_frame.setObjectName('panel'); video_frame.setLayout(self.video_holder)
        self.canvas=VideoCanvas(); self.video_holder.addWidget(self.canvas); left.addWidget(video_frame,1)
        self.message=QLabel('先在右侧填写连接信息；已有直播会自动接入。'); self.message.setWordWrap(True); self.message.setObjectName('muted'); left.addWidget(self.message)
        metrics=QHBoxLayout(); self.metrics={}
        for key,title in [('fps','编码帧率'),('size','采集尺寸'),('bitrate','目标码率'),('disk','板端剩余空间')]:
            self.metrics[key]=Metric(title); metrics.addWidget(self.metrics[key])
        left.addLayout(metrics)
        self.preview_stats=QLabel('电脑预览：等待画面'); self.preview_stats.setObjectName('muted'); left.addWidget(self.preview_stats)
        toolbar=QHBoxLayout(); self.action_buttons={}
        for action,text,name in [('start','▶ 启动直播','primary'),('stop','■ 停止直播',''),('snapshot','截图',''),('record-start','● 开始录像','primary'),('record-stop','■ 停止录像','danger')]:
            item=button(text,lambda checked=False,a=action:self.action(a),name); self.action_buttons[action]=item; toolbar.addWidget(item)
        left.addLayout(toolbar)
        bottom=QHBoxLayout(); self.record_clock=QLabel('未录像'); self.record_clock.setObjectName('muted'); bottom.addWidget(self.record_clock); bottom.addStretch()
        self.hdmi_button=button('HDMI 开启',self.toggle_hdmi); bottom.addWidget(self.hdmi_button); left.addLayout(bottom)
        panel=QFrame(); panel.setObjectName('panel'); panel.setFixedWidth(350); right=QVBoxLayout(panel); right.setContentsMargins(14,16,14,16)
        tabs=QGridLayout(); self.pages=QStackedWidget(); self.tab_buttons=[]
        for i,name in enumerate(('设备连接','编码设置','媒体文件','运行日志')):
            item=button(name,lambda checked=False,index=i:self.select_page(index),'tab'); item.setCheckable(True); tabs.addWidget(item,i//2,i%2); self.tab_buttons.append(item)
        right.addLayout(tabs); right.addWidget(self.pages,1); body.addWidget(panel)
        self.build_connection(); self.build_encoding(); self.build_media(auto); self.build_logs(); self.select_page(0)
        self.footer=QLabel('  单相机 · RTSP TCP · 关闭软件后板端任务继续运行'); self.footer.setObjectName('muted'); self.footer.setContentsMargins(22,6,22,14); outer.addWidget(self.footer)

    def page(self,title):
        content=QWidget(); content.setObjectName('page'); content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        layout=QVBoxLayout(content); layout.setContentsMargins(0,15,0,0); layout.setSpacing(12)
        label=QLabel(title); label.setObjectName('section'); layout.addWidget(label)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.pages.addWidget(scroll)
        return layout

    def build_connection(self):
        layout=self.page('连接你的开发板'); form=QFormLayout(); form.setSpacing(10)
        self.host=QLineEdit(self.connection.host); self.port=QSpinBox(); self.port.setRange(1,65535); self.port.setValue(self.connection.port)
        self.username=QLineEdit(self.connection.username); self.auth=QComboBox(); self.auth.addItems(['密码登录','密钥登录']); self.auth.setCurrentIndex(self.connection.auth=='key')
        self.secret=QLineEdit(); self.secret.setEchoMode(QLineEdit.EchoMode.Password); self.secret.setPlaceholderText('SSH 密码 / 私钥口令')
        self.key_file=QLineEdit(self.connection.key_file); key_row=QHBoxLayout(); key_row.addWidget(self.key_file); key_row.addWidget(button('选择',self.choose_key))
        for name,widget in [('板子地址',self.host),('SSH 端口',self.port),('用户名',self.username),('认证方式',self.auth),('密码 / 口令',self.secret)]: form.addRow(name,widget)
        form.addRow('私钥文件',key_row); layout.addLayout(form)
        self.remember=QCheckBox('记住密码（Windows 凭据管理器）'); self.remember.setChecked(self.connection.remember); layout.addWidget(self.remember)
        layout.addWidget(button('连接开发板',self.connect_board,'primary')); layout.addWidget(button('断开控制与电脑预览',self.disconnect_board))
        self.connection_note=QLabel('默认 SSH 端口 22。连接后先读取现有任务，已有直播不会重复启动。'); self.connection_note.setWordWrap(True); self.connection_note.setObjectName('muted'); layout.addWidget(self.connection_note)
        layout.addStretch()
        if self.connection.remember:
            try: self.secret.setText(keyring.get_password('EVM3588CameraConsole',self.connection.credential_id) or '')
            except Exception as error: self.add_log('连接',str(error))

    def build_encoding(self):
        layout=self.page('编码与采集参数'); form=QFormLayout(); form.setSpacing(9)
        self.codec=QComboBox(); self.codec.addItems(['H.265 / HEVC','H.264 / AVC'])
        self.width=QSpinBox(); self.width.setRange(96,3840); self.width.setSingleStep(8); self.width.setValue(1920)
        self.height=QSpinBox(); self.height.setRange(64,2160); self.height.setSingleStep(8); self.height.setValue(1080)
        self.fps=QSpinBox(); self.fps.setRange(1,60); self.fps.setValue(30)
        self.bitrate=QDoubleSpinBox(); self.bitrate.setRange(0.1,20); self.bitrate.setDecimals(2); self.bitrate.setSingleStep(0.5); self.bitrate.setSuffix(' Mbit/s'); self.bitrate.setValue(2.5)
        self.gop=QSpinBox(); self.gop.setRange(1,600); self.gop.setValue(30)
        self.device=QLineEdit('/dev/video44')
        for name,widget in [('编码格式',self.codec),('宽度',self.width),('高度',self.height),('帧率',self.fps),('CBR 码率',self.bitrate),('GOP 帧数',self.gop)]: form.addRow(name,widget)
        layout.addLayout(form); self.advanced=QCheckBox('高级：采集节点'); self.advanced.toggled.connect(self.device.setVisible); layout.addWidget(self.advanced); layout.addWidget(self.device); self.device.hide()
        self.apply_button=button('应用参数并重启直播',self.apply_config,'primary'); layout.addWidget(self.apply_button)
        layout.addWidget(button('读取当前运行参数',self.fill_config)); self.actual_text=QLabel('运行值：等待连接'); self.actual_text.setWordWrap(True); layout.addWidget(self.actual_text)
        note=QLabel('尺寸必须满足摄像头能力。修改参数会短暂中断画面；录像中需要先停止录像。失败时尝试恢复原直播。'); note.setWordWrap(True); note.setObjectName('muted'); layout.addWidget(note); layout.addStretch()

    def build_media(self,auto):
        layout=self.page('录像与截图文件'); self.table=QTableWidget(0,3); self.table.setHorizontalHeaderLabels(['文件名','大小','状态'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows); self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch); self.table.setColumnWidth(1,67); self.table.setColumnWidth(2,63)
        self.table.setMinimumHeight(220); layout.addWidget(self.table)
        row=QHBoxLayout(); self.refresh_files=button('刷新列表',lambda:self.files.submit('list')); self.download_button=button('下载所选',self.download_selected)
        row.addWidget(self.refresh_files); row.addWidget(self.download_button); layout.addLayout(row)
        self.download_path=QLineEdit(self.download_dir); layout.addWidget(QLabel('电脑保存目录')); layout.addWidget(self.download_path)
        row=QHBoxLayout(); row.addWidget(button('选择目录',self.choose_download)); row.addWidget(button('打开目录',self.open_download)); layout.addLayout(row)
        self.auto_download=QCheckBox('停止录像后自动下载'); self.auto_download.setChecked(auto); layout.addWidget(self.auto_download)
        self.progress=QProgressBar(); self.progress.setValue(0); layout.addWidget(self.progress)
        self.download_note=QLabel('截图会自动保存到电脑；录像先在板端封口。'); self.download_note.setWordWrap(True); self.download_note.setObjectName('muted'); layout.addWidget(self.download_note)
        layout.addWidget(button('取消当前下载',self.files.cancel.set))
        self.thumbnail=QLabel('最近截图'); self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter); self.thumbnail.setFixedHeight(130); self.thumbnail.setObjectName('muted'); layout.addWidget(self.thumbnail)
        self.open_local=button('打开最近下载的文件',self.open_last_file); layout.addWidget(self.open_local); layout.addStretch(); self.last_local=None

    def build_logs(self):
        layout=self.page('运行日志'); self.log_filter=QComboBox(); self.log_filter.addItems(['全部','系统','连接','控制','编码','录像','播放','文件'])
        self.log_filter.currentTextChanged.connect(self.render_logs); layout.addWidget(self.log_filter)
        self.log_view=QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(1000); self.log_view.setMinimumHeight(300); layout.addWidget(self.log_view,1)
        layout.addWidget(button('读取板端最近日志',lambda:self.ssh.submit('logs'))); layout.addWidget(button('复制当前日志',self.copy_logs)); layout.addWidget(button('打开本地日志目录',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_root())))))

    def connect_signals(self):
        self.ssh.connected.connect(self.on_connection); self.ssh.status.connect(self.on_status); self.ssh.result.connect(self.on_result)
        self.ssh.failure.connect(self.on_failure); self.ssh.host_key.connect(self.on_host_key); self.ssh.busy.connect(self.on_busy)
        self.video.state.connect(self.on_video_state); self.video.log.connect(lambda text:self.add_log('播放',text))
        self.files.listing.connect(self.on_listing); self.files.progress.connect(self.on_progress); self.files.completed.connect(self.on_download)
        self.files.failure.connect(lambda text:self.on_failure('download',text)); self.files.busy.connect(self.on_file_busy)

    def select_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,item in enumerate(self.tab_buttons): item.setChecked(i==index)

    def choose_key(self):
        file,_=QFileDialog.getOpenFileName(self,'选择 SSH 私钥')
        if file: self.key_file.setText(file); self.auth.setCurrentIndex(1)

    def connect_board(self):
        try:
            self.connection=Connection(self.host.text().strip(),self.port.value(),self.username.text().strip(),
                                       'key' if self.auth.currentIndex() else 'password',self.key_file.text().strip(),self.remember.isChecked()).validate()
            self.password=self.secret.text()
            if self.connection.remember:
                keyring.set_password('EVM3588CameraConsole',self.connection.credential_id,self.password)
            else:
                try: keyring.delete_password('EVM3588CameraConsole',self.connection.credential_id)
                except keyring.errors.PasswordDeleteError: pass
            self.save_settings(); self.files.configure(self.connection,self.password)
            self.want_board=True; self.have_config=False; self.ssh.submit('connect',(self.connection,self.password)); self.message.setText('正在连接 SSH 并查询板端状态…')
        except Exception as error: self.on_failure('connect',str(error))

    def disconnect_board(self):
        self.want_board=False
        self.ssh.submit('disconnect'); self.video.pause(); self.files.disconnect(); self.password=''
        self.board={}; self.ssh_connected=False; self.update_controls()
        self.badges['SSH'].set_state(False,'未连接')
        self.canvas.set_message('控制与电脑预览已断开；板端任务继续运行',clear=True)

    def on_host_key(self,details):
        reply=QMessageBox.question(self,'确认开发板身份',f"首次连接 {details['host']}\n\n主机指纹：\n{details['fingerprint']}\n\n确认这是你的开发板后保存该指纹？",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if reply==QMessageBox.StandardButton.Yes:
            try: trust_host(details); self.ssh.submit('connect',(self.connection,self.password))
            except Exception as error: self.on_failure('connect',str(error))
        else: self.message.setText('尚未信任主机，连接已取消。')

    def on_connection(self,connected,message):
        if self.closing or (connected and not self.want_board): return
        self.ssh_connected=connected; self.badges['SSH'].set_state(connected,'已连接' if connected else '未连接')
        self.connection_note.setText(message); self.add_log('连接',message); self.update_controls()
        if connected: self.files.configure(self.connection,self.password); self.files.submit('list')

    def on_busy(self,value): self.operation_busy=value; self.update_controls()
    def on_file_busy(self,value): self.file_busy=value; self.update_controls()

    def update_controls(self):
        state=controls(self.board,self.ssh_connected,self.operation_busy)
        for action,item in self.action_buttons.items(): item.setEnabled(state[action])
        self.apply_button.setEnabled(state['apply']); self.hdmi_button.setEnabled(state['hdmi'])
        self.refresh_files.setEnabled(self.ssh_connected and not self.file_busy); self.download_button.setEnabled(self.ssh_connected and not self.file_busy)
        self.hdmi_button.setText('HDMI 关闭' if self.board.get('previewRunning') else 'HDMI 开启')

    def action(self,action):
        if self.operation_busy or not self.ssh_connected: return
        if action=='stop' and self.board.get('recording'):
            if QMessageBox.question(self,'停止直播','停止直播会先结束正在进行的录像。继续？')!=QMessageBox.StandardButton.Yes: return
        if action=='stop': self.pending_stop_recording=bool(self.board.get('recording'))
        self.on_busy(True); self.ssh.submit(action); self.message.setText({'start':'正在启动直播…','stop':'正在停止直播并释放摄像头…','snapshot':'正在截图…','record-start':'正在开始录像…','record-stop':'正在结束录像并验证 MP4…'}.get(action,'正在执行操作…'))

    def toggle_hdmi(self): self.action('preview-stop' if self.board.get('previewRunning') else 'preview-start')

    def requested_config(self):
        return {'device':self.device.text().strip(),'codec':'h264' if self.codec.currentIndex() else 'h265',
                'width':self.width.value(),'height':self.height.value(),'fps':self.fps.value(),'bitrate':round(self.bitrate.value()*1000000),'gop':self.gop.value()}

    def apply_config(self):
        config=self.requested_config()
        if config['width']%8 or config['height']%8:
            self.on_failure('start','当前 ISP 尺寸步长为 8，请使用宽高均为 8 的倍数的尺寸'); return
        if self.board.get('recording'): self.on_failure('start','Stop and finalize recording'); return
        self.on_busy(True); self.ssh.submit('start',config); self.message.setText('正在应用参数，视频会短暂重连…')

    def fill_config(self):
        config=self.board.get('config',DEFAULT_CONFIG)
        self.codec.setCurrentIndex(config.get('codec')=='h264'); self.width.setValue(config.get('width',1920)); self.height.setValue(config.get('height',1080))
        self.fps.setValue(config.get('fps',30)); self.bitrate.setValue(config.get('bitrate',2500000)/1000000); self.gop.setValue(config.get('gop',30)); self.device.setText(config.get('device','/dev/video44'))

    def on_status(self,status):
        if self.closing or not self.want_board: return
        previous=self.board; self.board=status; ready=status.get('state')=='running'; config=status.get('config',{})
        self.badges['VPU'].set_state(bool(status.get('vpuDeviceOpen')),'硬编' if status.get('vpuDeviceOpen') else '未运行')
        self.badges['HDMI'].set_state(bool(status.get('previewRunning')),'已开启' if status.get('previewRunning') else '已关闭')
        self.badges['录像'].set_state(bool(status.get('recording')),'录制中' if status.get('recording') else '未录像')
        self.metrics['fps'].value.setText(f"{status.get('fps') or '—'} fps")
        actual=status.get('actualCapture') or {}; width=actual.get('width',config.get('width',1920)); height=actual.get('height',config.get('height',1080))
        self.metrics['size'].value.setText(f'{width}×{height}'); self.metrics['bitrate'].value.setText(f"{config.get('bitrate',0)/1000000:g} M")
        self.metrics['disk'].value.setText(f"{status.get('freeBytes',0)/1024**3:.1f} GiB")
        self.actual_text.setText(f"运行值：{config.get('codec','—').upper()} · {width}×{height}\n{config.get('fps','—')} fps · {config.get('bitrate',0)/1000000:g} Mbit/s · GOP {config.get('gop','—')}\n实际编码器：{status.get('encoder','—')}\n{'采集尺寸已确认' if actual else '采集尺寸等待板端报告'}")
        self.stream_text.setText(f"{config.get('codec','—').upper()} · {self.connection.rtsp_url}")
        self.footer.setText(f"  帧进度 {status.get('frame',0):,}   ·   丢帧 {status.get('droppedFrames') or 0}   ·   补帧 {status.get('duplicateFrames') or 0}   ·   订阅者 {status.get('readers',0)}   ·   状态更新时间 {datetime.now():%H:%M:%S}")
        if not getattr(self,'have_config',False): self.fill_config(); self.have_config=True
        if ready:
            token=(status.get('capturePid'),width,height,config.get('codec'))
            self.video.configure(self.connection.rtsp_url,width,height,token)
        elif previous.get('state')=='running': self.video.pause(); self.canvas.set_message('直播已停止或正在恢复',clear=True)
        error=status.get('lastError')
        if error and error!=self.last_history:
            self.last_history=error; self.add_log('编码','历史事件：'+str(error.get('message',error)))
        if ready and not self.operation_busy and time.monotonic()>=self.error_until: self.message.setText('直播正常；可以截图、录像或修改编码参数。')
        self.update_controls(); self.update_clock()

    def on_result(self,action,response):
        if getattr(self,'closing',False) or not getattr(self,'want_board',True): return
        if not response.get('ok'):
            recovery=response.get('result',{}).get('recovery',{})
            note='（原直播已恢复）' if recovery.get('restored') else ''
            self.on_failure(action,str(response.get('error'))+note); return
        result=response.get('result',{})
        if action=='check':
            item=self.codec.model().item(1); item.setEnabled('h264_rkmpp' in result.get('encoders',[]))
            self.add_log('系统','板端硬编能力：'+', '.join(result.get('encoders',[])))
            if result.get('sensorFramesPerSecond'): self.fps.setMaximum(min(60,int(result['sensorFramesPerSecond'])))
        elif action=='snapshot': self.files.submit('download',(result['file'],self.download_path.text())); self.files.submit('list')
        elif action in ('record-stop','stop'):
            if action=='stop' and result.get('recordingResult',{}).get('error'):
                self.on_failure('record-stop','直播已停止，但录像封口失败：'+str(result['recordingResult']['error']))
                self.files.submit('list'); return
            recording=result.get('lastRecording') or result.get('recordingResult',{}).get('lastRecording')
            if recording and self.auto_download.isChecked() and (action=='record-stop' or self.pending_stop_recording):
                self.files.submit('download',(recording['file'],self.download_path.text()))
            self.pending_stop_recording=False
            self.files.submit('list')
        elif action=='logs':
            for key,lines in result.items():
                for line in lines: self.add_log({'capture':'编码','recording':'录像','preview':'播放'}.get(key,'控制'),line)
        if action!='check': self.add_log('控制',action+' 已完成')

    def on_failure(self,action,text):
        category='文件' if action=='download' else ('连接' if action in ('connect','status') else '控制')
        self.add_log(category,text); self.message.setText(explain_error(text)); self.message.setToolTip(text)
        self.error_until=time.monotonic()+8

    def on_video_state(self,text):
        self.video_state=text; self.badges['视频'].set_state(text=='实时画面',text)
        if text!='实时画面': self.canvas.set_message(text)

    def render_frame(self):
        frame=self.video.take_frame()
        if frame: self.canvas.set_frame(frame[0],frame[1],frame[2]); self.displayed_frames+=1

    def change_preview_quality(self,quality):
        save_preview_quality(quality); self.video.set_quality(*PREVIEW_PRESETS[quality]); self.reconnect_video()
        self.add_log('播放',f'电脑预览切换为{quality}；板端直播和录像保持原参数。')

    def reconnect_video(self):
        self.video.pause()
        if self.board.get('state')=='running':
            config=self.board['config']; self.video.configure(self.connection.rtsp_url,config['width'],config['height'],(self.board.get('capturePid'),config['width'],config['height'],config['codec']))

    def enter_fullscreen(self):
        if self.fullscreen: return
        dialog=QDialog(self); dialog.setWindowTitle('实时视频 · Esc 返回'); layout=QVBoxLayout(dialog); layout.addWidget(self.canvas)
        layout.addWidget(button('返回控制台',dialog.reject)); dialog.finished.connect(self.leave_fullscreen); self.fullscreen=dialog; dialog.showFullScreen()

    def leave_fullscreen(self):
        if self.fullscreen: self.video_holder.addWidget(self.canvas); self.fullscreen.deleteLater(); self.fullscreen=None

    def update_clock(self):
        now=time.monotonic(); before,decoded,displayed=self.rate_sample; elapsed=max(0.001,now-before)
        if elapsed>=0.8: self.rate_sample=(now,self.video.frames,self.displayed_frames)
        if elapsed>=0.8 and self.video_state=='实时画面' and now-self.video.last_frame<4:
            startup=self.video.first_frame_seconds
            suffix=f' · 首帧 {startup:.2f}s' if startup is not None else ''
            self.preview_stats.setText(f'电脑预览 {self.video.width}×{self.video.height} · 解码 {(self.video.frames-decoded)/elapsed:.1f} fps · 显示 {(self.displayed_frames-displayed)/elapsed:.1f} fps · 重连 {self.video.reconnects}{suffix}')
        elif self.video_state!='实时画面': self.preview_stats.setText('电脑预览：'+self.video_state)
        started=self.board.get('recordingStartedAt')
        if started:
            try:
                elapsed=max(0,int(time.time()-datetime.fromisoformat(started).timestamp())); self.record_clock.setText(f'● 录像中  {elapsed//3600:02}:{elapsed//60%60:02}:{elapsed%60:02}')
            except ValueError: self.record_clock.setText('录像中')
        else: self.record_clock.setText('未录像 · 录像保存到板端，结束后可下载')

    def on_listing(self,rows):
        self.rows=rows; self.table.setRowCount(len(rows))
        for index,row in enumerate(rows):
            for column,text in enumerate((row['name'],f"{row['bytes']/1024**2:.1f} MB",'完成' if row['complete'] else '写入中')):
                item=QTableWidgetItem(text); item.setToolTip(row['path']); self.table.setItem(index,column,item)

    def download_selected(self):
        index=self.table.currentRow()
        if index<0: self.download_note.setText('请先选择要下载的文件。'); return
        row=self.rows[index]
        if not row['complete']: self.download_note.setText('录像仍在写入，请停止录像并等待封口。'); return
        self.save_settings(); self.files.submit('download',(row['path'],self.download_path.text()))

    def on_progress(self,remote,done,total):
        self.progress.setValue(int(done/max(1,total)*100)); self.download_note.setText(f'正在下载：{done/1024**2:.1f} / {total/1024**2:.1f} MB')

    def on_download(self,remote,local):
        self.last_local=local; self.local_files[remote]=local; self.progress.setValue(100); self.download_note.setText('SHA-256 校验通过，已保存：'+local); self.add_log('文件','下载与 SHA-256 校验完成：'+local)
        if local.lower().endswith('.jpg'): self.thumbnail.setPixmap(QPixmap(local).scaled(300,130,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))

    def choose_download(self):
        folder=QFileDialog.getExistingDirectory(self,'选择电脑保存目录',self.download_path.text())
        if folder: self.download_path.setText(folder); self.save_settings()
    def open_download(self):
        folder=Path(self.download_path.text()); folder.mkdir(parents=True,exist_ok=True); QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
    def open_last_file(self):
        if self.last_local:
            if self.last_local.lower().endswith('.mp4'):
                viewer=LocalVideoDialog(self.last_local,self); self.file_viewers.append(viewer); viewer.show()
            else: QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_local))
    def save_settings(self): save_preferences(self.connection,self.download_path.text(),self.auto_download.isChecked())

    def add_log(self,category,text):
        line=f'[{datetime.now():%H:%M:%S}] [{category}] {text}'; self.event_log.append((category,line)); self.event_log=self.event_log[-1000:]
        self.pending_logs.append((category,line)); self.pending_logs=self.pending_logs[-1000:]
    def flush_logs(self):
        if not self.pending_logs: return
        pending,self.pending_logs=self.pending_logs,[]
        try:
            path=data_root()/'console.log'
            if path.exists() and path.stat().st_size>2*1024*1024: path.replace(data_root()/'console.previous.log')
            with path.open('a',encoding='utf-8') as file: file.write('\n'.join(line for _,line in pending)+'\n')
        except OSError as error:
            self.message.setToolTip('本地日志写入失败：'+str(error))
        category=self.log_filter.currentText(); lines=[line for group,line in pending if category=='全部' or category==group]
        if lines:
            bar=self.log_view.verticalScrollBar(); follow=bar.value()>=bar.maximum()-2; position=bar.value()
            self.log_view.appendPlainText('\n'.join(lines)); bar.setValue(bar.maximum() if follow else position)
    def render_logs(self):
        self.flush_logs()
        category=self.log_filter.currentText(); lines=[line for group,line in self.event_log if category=='全部' or category==group]
        self.log_view.setPlainText('\n'.join(lines)); bar=self.log_view.verticalScrollBar(); bar.setValue(bar.maximum())
    def copy_logs(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def closeEvent(self,event):
        if not self.closing:
            self.closing=True; self.timer.stop(); self.clock.stop(); self.log_timer.stop(); self.save_settings(); self.flush_logs()
            self.centralWidget().setEnabled(False); self.message.setText('正在退出电脑连接与预览；板端任务继续运行…')
            for viewer in list(self.file_viewers): viewer.close()
            self.ssh.shutdown(); self.video.shutdown(); self.files.shutdown()
            self.close_timer=QTimer(self); self.close_timer.setInterval(100); self.close_timer.timeout.connect(self.finish_close); self.close_timer.start()
        if any(worker.isRunning() for worker in (self.ssh,self.video,self.files)) or self.file_viewers:
            event.ignore(); return
        self.close_timer.stop(); self.flush_logs()
        self.secret.clear(); self.password=''; event.accept()

    def finish_close(self):
        if not any(worker.isRunning() for worker in (self.ssh,self.video,self.files)) and not self.file_viewers: self.close()

class LocalVideoDialog(QDialog):
    def __init__(self,path,parent):
        super().__init__(parent); self.setWindowTitle('录像回放 · '+Path(path).name); self.resize(1000,650)
        layout=QVBoxLayout(self); self.canvas=VideoCanvas(); layout.addWidget(self.canvas,1)
        layout.addWidget(QLabel('本地 MP4 循环回放 · 关闭窗口结束播放'))
        self.worker=VideoWorker(); self.worker.state.connect(self.canvas.set_message)
        self.worker.configure(path,1280,720,('file',1280,720,path)); self.worker.start()
        self.timer=QTimer(self); self.timer.setTimerType(Qt.TimerType.PreciseTimer); self.timer.setInterval(33); self.timer.timeout.connect(self.render); self.timer.start()
    def render(self):
        frame=self.worker.take_frame()
        if frame: self.canvas.set_frame(frame[0],frame[1],frame[2])
    def closeEvent(self,event):
        self.timer.stop(); self.worker.shutdown()
        if not self.worker.isRunning():
            parent=self.parent()
            if parent is not None and hasattr(parent,'file_viewers') and self in parent.file_viewers: parent.file_viewers.remove(self)
            event.accept(); self.deleteLater()
        else:
            event.ignore()
            if not hasattr(self,'close_timer'):
                self.close_timer=QTimer(self); self.close_timer.setInterval(100); self.close_timer.timeout.connect(self.close_if_ready); self.close_timer.start()
    def close_if_ready(self):
        if not self.worker.isRunning(): self.close_timer.stop(); self.close()
