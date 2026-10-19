from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evm_console.video import rtsp_decoder_options


def test_performance_preview_does_not_disable_frame_threading():
    options = rtsp_decoder_options(60)
    assert 'low_delay' not in options
    assert 'frame' in options[options.index('-thread_type') + 1]
    assert options[options.index('-threads') + 1] == '4'


def test_normal_preview_retains_existing_low_delay_policy():
    options = rtsp_decoder_options(30)
    assert options[options.index('-flags') + 1] == 'low_delay'
    assert options[options.index('-threads') + 1] == '2'
