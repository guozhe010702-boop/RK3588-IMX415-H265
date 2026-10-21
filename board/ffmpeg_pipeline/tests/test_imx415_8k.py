import importlib.util
from pathlib import Path
import sys
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from imx415_8k import capture_arguments

spec = importlib.util.spec_from_file_location(
    "camera_fixture", HERE.parents[2] / "tools/tests/prepare_camera_8k60.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def test_real_camera_8k30_selects_without_duplicating():
    args = capture_arguments("encode30", 60, 600, Path("movie.mp4"))
    assert args[args.index("-i") + 1] == "/dev/video44"
    filters = args[args.index("-vf") + 1]
    assert "select=not(mod(n\\,2))" in filters
    assert "scale_rkrga=w=7680:h=4320" in filters
    assert "fps=fps=30" in filters
    assert filters.index("select=") < filters.index("fps=fps=30")
    assert "lavfi" not in args and "-r" not in args
    assert args[args.index("-c:v") + 1] == "hevc_rkmpp"


def test_insufficient_sensor_rate_rejected():
    with pytest.raises(ValueError):
        capture_arguments("capture60", 30, 600, Path("movie.mp4"))
    with pytest.raises(ValueError):
        capture_arguments("encode30", 20, 600, Path("movie.mp4"))


def test_capture60_never_upscales_or_adds_frames():
    args = capture_arguments("capture60", 60, 600, Path("movie.mp4"))
    assert "scale" not in args[args.index("-vf") + 1]
    assert "select=" not in args[args.index("-vf") + 1]
    assert "-r" not in args


def test_offline_conversion_preserves_time_and_uses_camera_file():
    args = fixture.arguments(Path("camera.mp4"), Path("out.mp4"), 120)
    assert args[args.index("-i") + 1] == "camera.mp4"
    assert "-r" not in args and "-stream_loop" not in args and "lavfi" not in args
    assert args[args.index("-fps_mode") + 1] == "passthrough"
    assert args[args.index("-vf") + 1] == "scale=7680:4320:flags=bilinear"


def test_unverified_camera_source_rejected(tmp_path):
    source = tmp_path / "fake.mp4"
    source.write_bytes(b"not camera")
    with pytest.raises(ValueError, match="verified real"):
        fixture.validate_camera(source, {"scope": "SYNTHETIC_CODEC_ONLY"}, {})


def test_continuous_preview_never_records_or_stops_at_frame_limit():
    args = capture_arguments("encode30", 60, 600, Path("unused.mp4"), rtsp=True, live=True)
    assert "-frames:v" not in args
    assert args[-1] == "rtsp://127.0.0.1:8555/imx415-upscaled-8k30"
    assert not any("mp4" in x for x in args)
    with pytest.raises(ValueError):
        capture_arguments("capture60", 60, 600, Path("unused.mp4"), live=True)


sys.path.insert(0, str(HERE.parents[2] / "tools/tests"))
import run_imx415_8k as preview


def test_preview_waits_for_a_readable_real_camera_stream(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    stream = {"codec_name": "hevc", "width": 7680, "height": 4320, "r_frame_rate": "30/1"}
    monkeypatch.setattr(
        preview.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps({"streams": [stream]}), stderr=""
        ),
    )
    assert preview.wait_preview_stream("ffprobe", "rtsp://board/path", tmp_path) == stream
    assert json.loads((tmp_path / "preview-stream.json").read_text()) == stream


def test_preview_connection_failure_keeps_diagnostics(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        preview.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Connection refused"),
    )
    monkeypatch.setattr(preview.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="preview-probe.log"):
        preview.wait_preview_stream("ffprobe", "rtsp://board/path", tmp_path)
    assert "Connection refused" in (tmp_path / "preview-probe.log").read_text()


def test_qsv_preview_keeps_full_decode_on_gpu_until_after_scaling():
    args = preview.qsv_decode_command("ffmpeg", "rtsp://board/path", Path("progress.txt"))
    assert args[args.index("-c:v") + 1] == "hevc_qsv"
    filters = args[args.index("-vf") + 1]
    assert filters.index("vpp_qsv=w=1280:h=720") < filters.index("hwdownload")
    player = preview.preview_command("ffplay", "rtsp://board/path", "intel-qsv")
    assert "-rtsp_transport" not in player
    assert player[-1] == "pipe:0" and "-noinfbuf" in player
    assert "-vf" not in player
