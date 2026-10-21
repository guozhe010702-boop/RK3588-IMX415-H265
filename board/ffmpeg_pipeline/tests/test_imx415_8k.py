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
