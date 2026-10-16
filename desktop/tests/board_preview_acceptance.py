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
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow


class AdbStatus(QThread):
    status = Signal(dict)
    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            start = time.monotonic()
            try:
                process = subprocess.run([str(ROOT.parent / 'Tools/platform-tools/adb.exe'), 'shell',
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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['EVM_CONSOLE_DATA'] = str((args.output / 'user-data').resolve())
    app = QApplication([])
    window = MainWindow()
    window.setWindowTitle('真实摄像头 RTSP / Qt 验证（USB 状态采样，非 SSH 验收）')
    window.preview_quality.setCurrentText('性能 60 fps')
    window.message.setText('真实板端 RTSP；USB 每秒查询指标。SSH 按钮在此测试中未连接。')
    window.show()
    window.select_page(4)
    rows = []
    window.performance.sample.connect(lambda row: rows.append(dict(row)))
    poll = AdbStatus()

    def update(state):
        window.performance.update_board(state, True)
        config = state.get('config', {})
        window.metrics['size'].value.setText('{}×{}'.format(config.get('width'), config.get('height')))
        window.badges['VPU'].set_state(state.get('vpuDeviceOpen'), '硬编')
        window.badges['HDMI'].set_state(state.get('previewRunning'), '硬解显示')
        window.badges['录像'].set_state(state.get('recording'), '录制中' if state.get('recording') else '未录像')
        if state.get('state') == 'running':
            window.video.configure('rtsp://192.168.2.221:8554/imx415', config['width'], config['height'],
                                   (state.get('capturePid'), config['width'], config['height']))
    poll.status.connect(update)
    poll.start()

    def finish():
        poll.stop_event.set()
        window.grab().save(str(args.output / 'console.png'))
        warm = rows[10:]
        keys = ['capture_fps', 'encode_fps', 'board_decode_fps', 'pc_decode_fps', 'qt_paint_fps',
                'rtsp_mbps', 'pc_session_mbps', 'nic_tx_mbps', 'gui_rss_mib', 'pc_decoder_rss_mib']
        summary = {'scope': 'real-camera-RTSP-Qt-with-USB-telemetry', 'real4k60Validated': False,
                   'seconds': args.seconds, 'samples': len(rows), 'averages': {}}
        for key in keys:
            values = [row[key] for row in warm if row.get(key) is not None]
            summary['averages'][key] = statistics.mean(values) if values else None
        summary['csv'] = window.performance.csv_path
        (args.output / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps(summary), flush=True)
        poll.wait(6000)
        window.close()

    QTimer.singleShot(args.seconds * 1000, finish)
    app.exec()


if __name__ == '__main__':
    main()
