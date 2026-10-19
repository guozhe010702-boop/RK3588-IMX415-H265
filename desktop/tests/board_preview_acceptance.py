"""Real RTSP/Qt test, with USB status sampling (does NOT claim SSH acceptance)."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'desktop'))
from PySide6.QtCore import QThread, Signal, QTimer, Qt
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow


class AdbStatus(QThread):
    status = Signal(dict)
    def __init__(self, adb):
        super().__init__()
        self.adb = adb
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                process = subprocess.run([str(self.adb), 'shell',
                    'python3', '/userdata/av_dev/ffmpeg_pipeline/avctl.py', 'status'],
                    capture_output=True, text=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                result = json.loads(process.stdout)
                if result.get('ok'):
                    self.status.emit(result['result'])
            except (ValueError, OSError, subprocess.TimeoutExpired):
                pass
            self.stop_event.wait(max(0.05, 1 - (time.monotonic() - start)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='rtsp://192.168.2.221:8554/imx415',
                        help='Actual RTSP endpoint; a USB forward is not a LAN acceptance test')
    parser.add_argument('--adb', type=Path, default=ROOT.parent / 'Tools/platform-tools/adb.exe')
    parser.add_argument('--keep-visible', action='store_true',
                        help='Keep this test window above other windows to avoid occluded-paint measurements')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['EVM_CONSOLE_DATA'] = str((args.output / 'user-data').resolve())
    app = QApplication([])
    window = MainWindow()
    if args.keep_visible:
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    window.setWindowTitle('真实摄像头 RTSP / Qt 验证：' + args.url)
    window.preview_quality.setCurrentText('性能 60 fps')
    window.message.setText('真实板端 RTSP；USB 每秒查询指标。SSH 按钮在此测试中未连接。')
    window.show()
    if args.keep_visible:
        # A launcher can supply a minimized initial Windows show state. Restore
        # once after the first show; never repeatedly override user minimization.
        QTimer.singleShot(200, window.showNormal)
    window.select_page(4)
    rows = []
    sample_file = (args.output / 'qt-samples.jsonl').open('w', encoding='utf-8')

    def collect(row):
        sample = dict(row, windowMinimized=window.isMinimized(),
                      windowVisible=window.isVisible(), windowActive=window.isActiveWindow())
        rows.append(sample)
        sample_file.write(json.dumps(sample) + '\n')
        sample_file.flush()

    window.performance.sample.connect(collect)
    poll = AdbStatus(args.adb)
    board_file = (args.output / 'board-samples.jsonl').open('w', encoding='utf-8')

    def update(state):
        board_file.write(json.dumps(state) + '\n')
        board_file.flush()
        window.performance.update_board(state, True)
        config = state.get('config', {})
        window.metrics['size'].value.setText('{}×{}'.format(config.get('width'), config.get('height')))
        window.badges['VPU'].set_state(state.get('vpuDeviceOpen'), '硬编')
        window.badges['HDMI'].set_state(state.get('previewRunning'), '硬解显示')
        window.badges['录像'].set_state(state.get('recording'), '录制中' if state.get('recording') else '未录像')
        if state.get('state') == 'running':
            window.video.configure(args.url, config['width'], config['height'],
                                   (state.get('capturePid'), config['width'], config['height']))
    poll.status.connect(update)
    poll.start()
    completed = [False]
    began = time.monotonic()

    def stop_poll():
        poll.stop_event.set()
        poll.wait(7000)
        sample_file.close()
        board_file.close()
        if not completed[0]:
            (args.output / 'interrupted.json').write_text(json.dumps({
                'scope': 'real-camera-RTSP-Qt-with-USB-telemetry', 'completed': False,
                'real4k60Validated': False, 'elapsedSeconds': time.monotonic() - began,
                'csv': window.performance.csv_path, 'url': args.url}, indent=2), encoding='utf-8')

    app.aboutToQuit.connect(stop_poll)

    def finish():
        completed[0] = True
        poll.stop_event.set()
        window.grab().save(str(args.output / 'console.png'))
        warm = rows[10:]
        keys = ['capture_fps', 'encode_fps', 'board_decode_fps', 'pc_decode_fps', 'qt_paint_fps',
                'rtsp_mbps', 'pc_session_mbps', 'nic_tx_mbps', 'gui_rss_mib', 'pc_decoder_rss_mib']
        summary = {'scope': 'real-camera-RTSP-Qt-with-USB-telemetry', 'real4k60Validated': False,
                   'url': args.url, 'keepVisible': args.keep_visible,
                   'seconds': args.seconds, 'samples': len(rows), 'averages': {}}
        for key in keys:
            values = [row[key] for row in warm if row.get(key) is not None]
            summary['averages'][key] = statistics.mean(values) if values else None
        summary['csv'] = window.performance.csv_path
        if warm:
            summary['minimizedSamplesAfterWarmup'] = sum(r.get('windowMinimized', False) for r in warm)
            errors = [r['pc_decode_errors'] for r in warm if r.get('pc_decode_errors') is not None]
            summary['pcDecodeErrorsAfterWarmup'] = errors[-1] - errors[0] if errors else None
            summary['firstFrameSeconds'] = next((r.get('first_frame_s') for r in warm if r.get('first_frame_s') is not None), None)
            summary['reconnects'] = max((r.get('reconnects') or 0 for r in warm), default=0)
        (args.output / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary), flush=True)
        poll.wait(6000)
        window.close()

    QTimer.singleShot(args.seconds * 1000, finish)
    app.exec()


if __name__ == '__main__':
    main()
