"""Background resource sampling and bounded, credential-free performance CSV."""

from collections import deque
import csv
import os
from datetime import datetime
from pathlib import Path
import threading
import time
import uuid
import psutil
from PySide6.QtCore import QThread, Signal
from .core import data_root


class Rates:
    def __init__(self):
        self.previous = {}
        self.baselines = {}

    def since(self, key, identity, value):
        if value is None:
            self.baselines.pop(key, None)
            return None, None
        old = self.baselines.get(key)
        if old is None or old[0] != identity or value < old[1]:
            old = self.baselines[key] = (identity, value)
        return value-old[1], old[1]

    def delta(self, key, identity, value, now):
        old = self.previous.pop(key, None)
        if value is None:
            return None
        self.previous[key] = (identity, value, now)
        if not old or old[0] != identity or value < old[1] or now <= old[2]:
            return None
        return (value - old[1]) / (now - old[2])


COLUMNS = ('time', 'board_stale', 'board_age_s', 'capture_fps', 'capture_gaps',
           'capture_new_gaps', 'capture_gap_baseline',
           'capture_buffers', 'capture_hold_max_ms', 'capture_age_max_ms',
           'capture_errors', 'sensor_fps', 'encode_fps', 'encode_frames', 'encode_drops',
           'encode_duplicates', 'board_decoder_name', 'board_decoder_vpu_open', 'board_decode_fps', 'board_decode_size', 'board_decode_running', 'board_decode_error', 'hdmi_size', 'monitor_mode',
           'pc_decode_fps', 'pc_decode_size', 'qt_paint_fps', 'window_minimized', 'preview_size',
           'preview_discarded', 'pc_decode_errors', 'reconnects', 'first_frame_s', 'video_age_s', 'target_mbps',
           'rtsp_mbps', 'pc_session_mbps', 'pc_session_link_percent', 'nic_name', 'nic_tx_mbps', 'nic_rx_mbps', 'link_mbps',
           'nic_tx_percent', 'nic_rx_percent', 'board_cpu_percent',
           'board_memory_percent', 'board_memory_used_gib', 'board_memory_total_gib',
           'pc_memory_percent', 'pc_memory_used_gib', 'pc_memory_total_gib', 'board_encoder_cpu_percent',
           'board_encoder_rss_mib', 'board_decoder_cpu_percent', 'board_decoder_rss_mib',
           'pc_cpu_percent', 'gui_cpu_percent', 'gui_rss_mib', 'pc_decoder_cpu_percent',
           'pc_decoder_rss_mib', 'board_temperature_c', 'vpu_frequencies', 'bottleneck')


def size_text(value):
    return 'x'.join(map(str, value)) if value else None


def flatten(board, video, local, rates, now, painted, paint_identity, received_at, connected,
            window_minimized=False):
    m = board.get('metrics') or {}
    board_age = max(0, now - received_at) + (m.get('ageSeconds') or 0) if m and received_at else None
    stale = not connected or not m or bool(m.get('stale')) or board_age is None or board_age > 3
    fresh = {} if stale else m
    capture = fresh.get('capture', {})
    new_gaps, gap_baseline = rates.since('capture-gaps', board.get('capturePid'),
        capture.get('sequenceGaps') if not capture.get('stale', True) else None)
    decoder = fresh.get('decoder', {})
    sessions = [s for s in fresh.get('clients', []) if s.get('clientId') == video['clientId']]
    session_rate = (sum(s['mbps'] for s in sessions)
                    if sessions and all(s.get('mbps') is not None for s in sessions) else None)
    interfaces = fresh.get('interfaces', [])
    # Use the active wired interface with the highest TX; do not mix WLAN and Ethernet totals.
    wired = [item for item in interfaces if item.get('linkMbps') and item.get('name', '').startswith(('eth', 'en'))]
    nic = max(wired, key=lambda x: x.get('txMbps') or 0) if wired else {}
    video_age = now - video['lastFrame'] if video['lastFrame'] else None
    decoding = video_age is not None and video_age < 4 and video.get('pid') is not None
    decoded = rates.delta('decoded', video['generation'], video['decodedFrames'] if decoding else None, now)
    painted_fps = rates.delta('paint', paint_identity, painted if decoding else None, now)
    config = board.get('config', {})
    result = dict.fromkeys(COLUMNS)
    monitor = decoder.get('monitorMode') or {}
    result.update(time=datetime.now().astimezone().isoformat(), board_stale=stale,
        board_age_s=board_age, capture_fps=None if capture.get('stale') else capture.get('fps'),
        capture_gaps=capture.get('sequenceGaps'), capture_errors=capture.get('errors'),
        capture_new_gaps=new_gaps, capture_gap_baseline=gap_baseline,
        capture_buffers=capture.get('buffers'),
        capture_hold_max_ms=capture['maxHoldUs'] / 1000 if capture.get('maxHoldUs') is not None else None,
        capture_age_max_ms=capture['maxAgeUs'] / 1000 if capture.get('maxAgeUs') is not None else None,
        sensor_fps=(board.get('actualCapture') or {}).get('reportedFps') if not stale else None,
        encode_fps=fresh.get('encoderFps'), encode_frames=board.get('frame') if not stale else None,
        encode_drops=board.get('droppedFrames') if not stale else None,
        encode_duplicates=board.get('duplicateFrames') if not stale else None,
        board_decode_fps=decoder.get('fps'), board_decode_size=size_text(decoder.get('inputSize')),
        board_decoder_name=decoder.get('decoder'), board_decoder_vpu_open=decoder.get('vpuDeviceOpen'),
        board_decode_running=decoder.get('running'), board_decode_error=decoder.get('error'),
        hdmi_size=size_text(decoder.get('displaySize')),
        monitor_mode=('{}x{}@{}Hz'.format(monitor['width'], monitor['height'], monitor['refreshHz']) if monitor else None),
        pc_decode_fps=decoded, pc_decode_size=size_text(video.get('inputSize')),
        qt_paint_fps=painted_fps, window_minimized=window_minimized,
        preview_size=size_text(video.get('previewSize')),
        preview_discarded=video['discarded'], reconnects=video['reconnects'],
        pc_decode_errors=video.get('decodeErrors'),
        first_frame_s=video.get('firstFrameSeconds'), video_age_s=video_age,
        target_mbps=config.get('bitrate', 0) / 1e6 if config else None,
        rtsp_mbps=fresh.get('rtspMbps'), pc_session_mbps=session_rate,
        pc_session_link_percent=session_rate/nic['linkMbps']*100 if session_rate is not None and nic.get('linkMbps') else None,
        nic_name=nic.get('name'), nic_tx_mbps=nic.get('txMbps'), nic_rx_mbps=nic.get('rxMbps'), link_mbps=nic.get('linkMbps'),
        nic_tx_percent=nic.get('txUtilizationPercent'), nic_rx_percent=nic.get('rxUtilizationPercent'),
        board_cpu_percent=fresh.get('hostCpuPercent'),
        board_memory_percent=fresh.get('hostMemory', {}).get('percent'),
        board_memory_used_gib=fresh['hostMemory']['usedBytes'] / 1024**3 if fresh.get('hostMemory', {}).get('usedBytes') is not None else None,
        board_memory_total_gib=fresh['hostMemory']['totalBytes'] / 1024**3 if fresh.get('hostMemory', {}).get('totalBytes') is not None else None,
        board_temperature_c=max((t['celsius'] for t in fresh.get('temperatures', [])), default=None),
        vpu_frequencies=';'.join('{}={}'.format(v['name'], v['frequencyHz']) for v in fresh.get('vpu', [])) or None)
    for name in ('encoder', 'decoder'):
        proc = fresh.get('processes', {}).get(name, {})
        result['board_' + name + '_cpu_percent'] = proc.get('cpuPercent')
        rss = proc.get('rssBytes')
        result['board_' + name + '_rss_mib'] = rss / 1024**2 if rss is not None else None
    result.update(local)
    result['bottleneck'] = ('板端指标已过期' if stale else
        '窗口已最小化：未进行可见绘制，板端任务继续' if window_minimized else
        '视频未出帧或已停滞' if not decoding else
        '60 fps 预览绘制不足 55 fps（请结合趋势判断）' if min(video.get('maximumFps', 30),
            video.get('sourceFps') or config.get('fps', 0)) >= 59
        and painted_fps is not None and painted_fps < 55 else '')
    return result


class PerformanceWorker(QThread):
    sample = Signal(dict)
    failure = Signal(str)

    def __init__(self, video, canvas):
        super().__init__()
        self.video, self.canvas = video, canvas
        self.lock = threading.Lock()
        self.board, self.received_at, self.connected = {}, 0, False
        self.window_minimized = False
        self.stop_event = threading.Event()
        self.folder = data_root() / 'performance'
        self.csv_path = None
        self.rates = Rates()
        self.processes = {}
        self.run_id = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]

    def update_board(self, board, connected):
        with self.lock:
            self.board, self.received_at, self.connected = board, time.monotonic(), connected

    def set_connected(self, connected):
        with self.lock:
            self.connected = connected

    def set_window_minimized(self, minimized):
        with self.lock:
            self.window_minimized = bool(minimized)

    def set_folder(self, folder):
        with self.lock:
            self.folder = Path(folder)

    def resources(self, pid):
        if not pid:
            return None, None
        try:
            new = pid not in self.processes
            if new:
                self.processes[pid] = psutil.Process(pid)
            proc = self.processes[pid]
            cpu = proc.cpu_percent()
            return None if new else cpu, proc.memory_info().rss / 1024**2
        except (psutil.Error, OSError):
            self.processes.pop(pid, None)
            return None, None

    def run(self):
        file = writer = None
        current_folder = None
        retry_at = 0
        csv_error = None
        psutil.cpu_percent()
        try:
            while not self.stop_event.is_set():
                start = time.monotonic()
                row = None
                try:
                    with self.lock:
                        board, received, connected, folder = self.board, self.received_at, self.connected, self.folder
                        minimized = self.window_minimized
                    video = self.video.metrics_snapshot()
                    video['discarded'] += self.canvas.discarded_frames
                    gui_cpu, gui_rss = self.resources(os.getpid())
                    dec_cpu, dec_rss = self.resources(video['pid'])
                    active_pids = {os.getpid(), video['pid']}
                    self.processes = {pid: p for pid, p in self.processes.items() if pid in active_pids}
                    local = dict(pc_cpu_percent=psutil.cpu_percent(), gui_cpu_percent=gui_cpu,
                        gui_rss_mib=gui_rss, pc_decoder_cpu_percent=dec_cpu, pc_decoder_rss_mib=dec_rss)
                    memory = psutil.virtual_memory()
                    local.update(pc_memory_percent=100*(memory.total-memory.available)/memory.total,
                        pc_memory_used_gib=(memory.total-memory.available)/1024**3,
                        pc_memory_total_gib=memory.total/1024**3)
                    row = flatten(board, video, local, self.rates, start, self.canvas.painted_frames,
                                  video['generation'], received, connected, minimized)
                    if current_folder != folder:
                        retry_at = 0
                    if (file is None or current_folder != folder) and start >= retry_at:
                        if file:
                            file.close()
                        folder.mkdir(parents=True, exist_ok=True)
                        # A new file on each directory selection, never truncate an existing run.
                        path = folder / ('performance-' + self.run_id + '-' + uuid.uuid4().hex[:4] + '.csv')
                        file = path.open('x', encoding='utf-8-sig', newline='')
                        writer = csv.DictWriter(file, fieldnames=COLUMNS)
                        writer.writeheader()
                        current_folder, self.csv_path = folder, str(path)
                        csv_error = None
                    if file:
                        writer.writerow(row)
                        file.flush()
                    row['csv_path'] = self.csv_path
                    if csv_error:
                        row['csv_error'] = csv_error
                    self.sample.emit(row)
                except Exception as error:
                    # Storage failures do not suppress visible telemetry or stop video.
                    if row is not None:
                        self.sample.emit(dict(row, csv_path=self.csv_path, csv_error=str(error)))
                    self.failure.emit(str(error))
                    if file:
                        file.close()
                    file = None
                    current_folder = folder
                    retry_at = start + 30
                    csv_error = str(error)
                self.stop_event.wait(max(0.05, 1 - (time.monotonic() - start)))
        finally:
            if file:
                file.close()

    def shutdown(self):
        self.stop_event.set()
