"""Visible Qt decode/paint benchmark. Local synthetic input is never camera proof."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_file() or args.seconds < 5:
        parser.error('Existing synthetic MP4 and at least five seconds required')
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['EVM_CONSOLE_DATA'] = str((args.output / 'user-data').resolve())
    app = QApplication([])
    window = MainWindow()
    window.setWindowTitle('离线合成 4K60 解码/Qt 验证（非摄像头、非板端硬编）')
    window.message.setText('测试本地合成 H.265 文件；不代表真实摄像头、RTSP 或 VPU 已验收。')
    window.preview_quality.setCurrentText('性能 60 fps')
    rows = []
    window.performance.sample.connect(lambda row: rows.append(dict(row)))
    window.show()
    window.select_page(4)
    window.video.configure(str(args.source.resolve()), 3840, 2160, ('offline-synthetic',))
    start = time.monotonic()

    def finish():
        window.grab().save(str(args.output / 'console.png'))
        warm = rows[5:]
        def mean(key):
            values = [r[key] for r in warm if r.get(key) is not None]
            return statistics.mean(values) if values else None
        summary = {'scope': 'synthetic-local-PC-software-decode-and-Qt-only',
            'realCamera4k60Validated': False, 'boardHardwareValidated': False,
            'durationSeconds': time.monotonic() - start, 'samples': len(rows),
            'decodeFps': mean('pc_decode_fps'), 'qtPaintFps': mean('qt_paint_fps'),
            'decoderCpuPercent': mean('pc_decoder_cpu_percent'), 'guiCpuPercent': mean('gui_cpu_percent'),
            'decoderRssMiB': mean('pc_decoder_rss_mib'), 'guiRssMiB': mean('gui_rss_mib'),
            'previewDiscarded': window.video.discarded, 'reconnects': window.video.reconnects,
            'csv': window.performance.csv_path, 'decodeSize': window.video.input_size,
            'previewSize': [window.video.width, window.video.height]}
        (args.output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary), flush=True)
        window.close()

    QTimer.singleShot(args.seconds * 1000, finish)
    app.exec()


if __name__ == '__main__':
    main()
