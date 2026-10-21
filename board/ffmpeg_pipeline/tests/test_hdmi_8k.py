import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.decoder import HardwareDisplay


def start_display(tmp_path, timestamped):
    (tmp_path / "logs").mkdir()
    host = SimpleNamespace(
        root=tmp_path,
        ffmpeg="private-ffmpeg",
        environment={},
        config={"width": 7680, "height": 4320, "codec": "h265", "fps": 30},
        active=lambda p: p is not None and p.poll() is None,
        stop_child=lambda *a: None,
    )
    decoder = SimpleNamespace(pid=123, stdout=io.BytesIO(), stderr=io.BytesIO(), poll=lambda: None)
    player = SimpleNamespace(pid=124, poll=lambda: None)
    screen = "HDMI-1 connected primary 1920x1080+0+0\n   1920x1080 60.00*+\n"
    url = "rtsp://127.0.0.1:8555/imx415-upscaled-8k30"
    display = HardwareDisplay(host, source_url=url, timestamped=timestamped, fullscreen=True)
    with patch(
        "camera_control.decoder.subprocess.run", return_value=SimpleNamespace(stdout=screen)
    ), patch("camera_control.decoder.subprocess.Popen", side_effect=[decoder, player]), patch(
        "camera_control.decoder.threading.Thread"
    ), patch(
        "camera_control.decoder.time.sleep"
    ):
        display.start()
    commands = json.loads((tmp_path / "logs/preview-commands.json").read_text())
    return display, commands, decoder


def test_hdmi_consumes_8k_bitstream_and_scales_after_hardware_decode(tmp_path):
    display, commands, _ = start_display(tmp_path, True)
    args = commands["decoder"]
    assert args[args.index("-c:v") + 1] == "hevc_rkmpp"
    assert args[args.index("-i") + 1].endswith("8555/imx415-upscaled-8k30?role=hdmi")
    assert "drm_prime" in args
    assert (
        args[args.index("-vf") + 1]
        == "scale_rkrga=w=1920:h=1080:format=nv12,hwdownload,format=nv12"
    )
    assert display.display_size == [1920, 1080]
    assert "-f" in args and "nut" in args
    assert "-framerate" not in commands["player"]
    assert "-noinfbuf" in commands["player"] and "-fs" in commands["player"]
    assert "/dev/video44" not in args


def test_raw_pipe_compatibility_is_retained(tmp_path):
    _, commands, _ = start_display(tmp_path, False)
    args = commands["player"]
    assert args[args.index("-framerate") + 1] == "30"
    assert args[args.index("-video_size") + 1] == "1920x1080"
    assert commands["decoder"][-3:] == ["-f", "rawvideo", "pipe:1"]


def test_reported_decode_input_remains_8k_after_1080p_scaling(tmp_path):
    display, _, decoder = start_display(tmp_path, True)
    decoder.stderr = io.BytesIO(
        b"Stream #0:0: Video: hevc (Main), yuv420p, 7680x4320\n"
        b"Stream #0:0: Video: rawvideo, nv12, 1920x1080\nframe=30\n"
    )
    display.read(decoder)
    assert display.input_size == [7680, 4320]
    assert display.display_size == [1920, 1080]
    assert display.frame == 30


def test_existing_controller_keeps_its_original_rtsp_endpoint():
    display = HardwareDisplay(SimpleNamespace())
    assert display.source_url == "rtsp://127.0.0.1:8554/imx415"
    assert display.timestamped is False
