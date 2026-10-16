import csv
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evm_console.telemetry import Rates, flatten, PerformanceWorker, COLUMNS
from evm_console.widgets import VideoCanvas
from evm_console.video import VideoWorker
from evm_console.core import FrameAssembler, PERFORMANCE_CONFIG
from PySide6.QtWidgets import QApplication


def video(**changes):
    return dict(clientId='a'*32, generation=(1, 10), pid=10, decodedFrames=120,
                discarded=3, lastFrame=10, inputSize=[3840, 2160], previewSize=[1280, 720],
                reconnects=0, maximumFps=60, firstFrameSeconds=0.5, **changes)


def test_counter_delta_reset_missing_and_restart():
    rates = Rates()
    assert rates.delta('fps', 1, 120, 1) is None
    assert rates.delta('fps', 1, 180, 2) == 60
    assert rates.delta('fps', 1, 2, 3) is None
    assert rates.delta('fps', 2, 62, 4) is None
    assert rates.delta('fps', 2, None, 5) is None
    assert rates.delta('fps', 2, 122, 6) is None


def test_missing_stale_and_client_association():
    rates = Rates()
    board = {'config': PERFORMANCE_CONFIG, 'frame': 120, 'metrics': {
        'stale': False, 'ageSeconds': 0.2, 'encoderFps': 60, 'rtspMbps': 20,
        'capture': {'fps': 59.9, 'stale': False},
        'clients': [{'clientId': 'a'*32, 'mbps': 20}, {'clientId': 'b'*32, 'mbps': 90}]}}
    row = flatten(board, video(), {}, rates, 10, 40, 1, 10, True)
    assert row['pc_session_mbps'] == 20
    assert row['capture_fps'] == 59.9 and row['qt_paint_fps'] is None
    row = flatten(board, video(), {}, rates, 11, 65, 1, 11, True)
    assert row['pc_decode_fps'] == 0 and row['qt_paint_fps'] == 25
    assert row['board_decoder_rss_mib'] is None
    row = flatten(board, video(), {}, rates, 15, 65, 1, 10, True)
    assert row['board_stale'] and row['encode_fps'] is None and row['pc_session_mbps'] is None
    assert row['pc_decode_fps'] is None


def test_only_new_frames_are_painted():
    app = QApplication.instance() or QApplication([])
    canvas = VideoCanvas()
    canvas.resize(500, 300)
    canvas.show()
    canvas.set_frame(bytes(48), 4, 4)
    app.processEvents()
    assert canvas.painted_frames == 1
    canvas.repaint()
    app.processEvents()
    assert canvas.painted_frames == 1
    canvas.set_frame(bytes(48), 4, 4)
    canvas.set_frame(bytes(48), 4, 4)
    app.processEvents()
    assert canvas.submitted_frames == 3 and canvas.painted_frames == 2
    assert canvas.discarded_frames == 1
    canvas.close()


def test_frame_assembler_counts_complete_and_discarded():
    assembler = FrameAssembler(6)
    assert assembler.feed(b'a'*19) == b'a'*6
    assert assembler.complete_frames == 3 and assembler.discarded_frames == 2
    assert len(assembler.buffer) == 1


def test_decoder_counts_before_preview_filter_without_logging_every_frame():
    import io
    worker = VideoWorker()
    lines = ('[showinfo@decoded @ 0001] n:   0 pts: 0 s:3840x2160\n'
             '[showinfo@decoded @ 0001] n:  59 pts: 59 s:3840x2160\n')
    worker.drain_log(SimpleNamespace(stderr=io.BytesIO(lines.encode())), 0)
    result = worker.metrics_snapshot()
    assert result['decodedFrames'] == 60 and result['inputSize'] == [3840, 2160]
    assert worker.frames == 0


def test_csv_is_complete_and_excludes_credentials(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('EVM_CONSOLE_DATA', str(tmp_path))
    worker = PerformanceWorker(VideoWorker(), SimpleNamespace(painted_frames=0, discarded_frames=0))
    worker.update_board({'password': 'MUST-NOT-APPEAR'}, True)
    worker.start()
    deadline = time.monotonic() + 3
    while worker.csv_path is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    worker.shutdown()
    assert worker.wait(3000)
    text = Path(worker.csv_path).read_text(encoding='utf-8-sig')
    rows = list(csv.DictReader(text.splitlines()))
    assert len(rows) >= 1 and set(rows[0]) == set(COLUMNS)
    assert 'MUST-NOT-APPEAR' not in text and 'password' not in text


def test_performance_preset_preserves_default():
    from evm_console.core import DEFAULT_CONFIG
    assert PERFORMANCE_CONFIG['fps'] == 60 and PERFORMANCE_CONFIG['bitrate'] == 20000000
    assert DEFAULT_CONFIG['fps'] == 30 and DEFAULT_CONFIG['width'] == 1920


def test_30fps_source_with_60fps_preview_is_not_a_55fps_bottleneck():
    v = video()
    v['sourceFps'] = 30
    rates = Rates()
    board = {'config': dict(PERFORMANCE_CONFIG, fps=30), 'metrics': {'stale': False, 'ageSeconds': 0}}
    flatten(board, v, {}, rates, 10, 30, 1, 10, True)
    row = flatten(board, v, {}, rates, 11, 60, 1, 11, True)
    assert row['qt_paint_fps'] == 30 and row['bottleneck'] == ''
