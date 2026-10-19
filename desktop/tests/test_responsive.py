"""Small work areas must keep actions reachable; preview must preserve pixels."""
import gc
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow
from evm_console.widgets import VideoCanvas
from test_layout import close_window


def test_narrow_window_can_reach_controls_and_all_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("EVM_CONSOLE_DATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(760, 480)
        window.show()
        app.processEvents()
        assert window.size().width() == 760
        root = window.root_scroll.widget()
        for index in range(window.pages.count()):
            window.select_page(index)
            app.processEvents()
            assert window.side_panel.maximumWidth() > 10000
            scroll = window.pages.currentWidget()
            assert scroll.widget().size().height() <= scroll.viewport().height() + scroll.verticalScrollBar().maximum()
        for widget in [*window.action_buttons.values(), window.hdmi_button, window.record_clock]:
            top = widget.mapTo(root, widget.rect().topLeft())
            assert top.y() + widget.size().height() <= root.size().height()
            assert widget.size().width() > 40
        window.content_splitter.setSizes([390, 330])
        app.processEvents()
        assert window._grid_columns == (2, 3)
        window.resize(1420, 900)
        window.content_splitter.setSizes([850, 500])
        app.processEvents()
        assert window._grid_columns == (4, 5)
    finally:
        close_window(app, window)


def test_preview_owns_rgb_bytes_and_counts_only_new_paints():
    app = QApplication.instance() or QApplication([])
    canvas = VideoCanvas()
    # Two rows of red/blue BGR pixels; unaligned 6-byte lines must stay intact.
    pixels = bytes([0, 0, 255, 255, 0, 0] * 2)
    canvas.set_frame(pixels, 2, 2)
    del pixels
    gc.collect()
    assert canvas.image.pixelColor(0, 0).name() == "#ff0000"
    assert canvas.image.pixelColor(1, 1).name() == "#0000ff"
    canvas.resize(400, 200)
    canvas.show()
    app.processEvents()
    painted = canvas.painted_frames
    rendered = canvas.grab().toImage()
    assert rendered.pixelColor(5, 100).name() == "#070e19"  # pillarbox
    assert rendered.pixelColor(140, 100).name() == "#ff0000"
    canvas.update()
    app.processEvents()
    assert canvas.painted_frames == painted
    canvas.set_message("断流", clear=True)
    assert canvas.image is None and canvas._pixels is None
    canvas.close()


def test_resource_overview_and_trend_axes_are_separate_widgets(tmp_path, monkeypatch):
    monkeypatch.setenv("EVM_CONSOLE_DATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        from evm_console.performance import update_overview
        window.show()
        window.select_page(4)
        row = {'board_stale': False, 'nic_tx_percent': 2.04, 'nic_tx_mbps':20.4,
            'link_mbps':1000, 'pc_session_mbps':20.2, 'board_cpu_percent':32,
            'pc_cpu_percent':9, 'board_memory_percent':25, 'pc_memory_percent':60,
            'qt_paint_fps':59.8, 'pc_decode_fps':60, 'video_age_s':0.1,
            'capture_fps':60, 'encode_fps':60, 'board_decode_fps':60}
        update_overview(window, row)
        assert window.performance_cards['nic'].value.text() == '2.04%'
        assert window.performance_cards['stream'].value.text() == '20.2 Mbit/s'
        assert window.performance_cards['board_cpu'].value.text() == '32.0%'
        window.trend_toggle.click()
        window.fps_trend.append(row)
        app.processEvents()
        plot = window.fps_trend.plot
        assert plot.geometry_for_plot().bottom()+29 <= plot.size().height()
        assert len(window.fps_trend.legend) == 4
        assert not window.performance_detail.isVisible()
        window.details_toggle.click()
        app.processEvents()
        assert window.performance_detail.isVisible()
        update_overview(window, dict(row, board_stale=True))
        assert window.performance_cards['nic'].value.text() == '已过期'
        assert window.performance_cards['pc_cpu'].value.text() == '9.0%'
    finally:
        close_window(app, window)
