"""Prepare labelled synthetic 8K fixtures on a PC, never camera validation.

Software HEVC generation is OFFLINE. Its speed is not RK3588 encoding evidence.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

WIDTH, HEIGHT = 7680, 4320
FRAME_BYTES = WIDTH * HEIGHT * 3 // 2


def run(args, log):
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.run(args, stdout=output, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError("Fixture creation failed; see " + str(log))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--raw-frames", type=int, default=8)
    p.add_argument("--decode-frames", type=int, default=120)
    p.add_argument("--ffmpeg", default="ffmpeg")
    p.add_argument("--ffprobe", default="ffprobe")
    a = p.parse_args()
    if not 2 <= a.raw_frames <= 60 or not 60 <= a.decode_frames <= 1800:
        p.error("raw frames 2..60; decode frames 60..1800")
    a.output.mkdir(parents=True, exist_ok=True)
    raw = a.output / "synthetic-8k30.nv12"
    movie = a.output / "synthetic-8k60.mp4"
    font = next(
        (
            p
            for p in [
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            ]
            if p.is_file()
        ),
        None,
    )
    if font is None:
        raise RuntimeError("Arial/DejaVu font not found for synthetic watermark")
    fontpath = font.as_posix().replace(":", r"\:")
    marker = (
        "drawtext=fontfile='"
        + fontpath
        + "':text='SYNTHETIC 8K - NOT CAMERA - %{n}':fontsize=96:fontcolor=white:box=1:boxcolor=black@0.7:x=64:y=64"
    )
    common = [
        a.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-filter_threads",
        "2",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=7680x4320:rate=60",
        "-an",
    ]
    raw_args = common + [
        "-frames:v",
        str(a.raw_frames),
        "-vf",
        marker + ",format=nv12",
        "-threads:v",
        "2",
        "-c:v",
        "rawvideo",
        "-f",
        "rawvideo",
        str(raw),
    ]
    movie_args = common + [
        "-frames:v",
        str(a.decode_frames),
        "-vf",
        marker + ",format=yuv420p",
        "-c:v",
        "libx265",
        "-preset",
        "ultrafast",
        "-b:v",
        "12M",
        "-g",
        "60",
        "-bf",
        "0",
        "-x265-params",
        "pools=4:frame-threads=2:level-idc=6.1:log-level=warning",
        "-tag:v",
        "hvc1",
        str(movie),
    ]
    print("Preparing 8K NV12 pattern; then offline 8K60 HEVC. Logs in " + str(a.output), flush=True)
    run(raw_args, a.output / "prepare-raw.log")
    assert raw.stat().st_size == FRAME_BYTES * a.raw_frames
    print("Raw fixture ready: " + str(raw.stat().st_size) + " bytes", flush=True)
    run(movie_args, a.output / "prepare-decode60.log")
    result = subprocess.check_output(
        [
            a.ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,nb_read_frames",
            "-of",
            "json",
            str(movie),
        ],
        text=True,
    )
    stream = json.loads(result)["streams"][0]
    assert (
        stream["width"] == WIDTH and stream["height"] == HEIGHT and stream["r_frame_rate"] == "60/1"
    )
    assert int(stream["nb_read_frames"]) == a.decode_frames

    def sha(path):
        h = hashlib.sha256()
        with path.open("rb") as f:
            for data in iter(lambda: f.read(1024 * 1024), b""):
                h.update(data)
        return h.hexdigest()

    manifest = {
        "scope": "SYNTHETIC_CODEC_ONLY",
        "realCameraValidated": False,
        "width": WIDTH,
        "height": HEIGHT,
        "frameBytesNV12": FRAME_BYTES,
        "raw": {
            "file": raw.name,
            "frames": a.raw_frames,
            "intendedEncoderFps": 30,
            "bytes": raw.stat().st_size,
            "sha256": sha(raw),
        },
        "decode60": {
            "file": movie.name,
            "fps": 60,
            "frames": a.decode_frames,
            "bytes": movie.stat().st_size,
            "sha256": sha(movie),
        },
        "commands": {"raw": raw_args, "offlineDecodeFixture": movie_args},
    }
    (a.output / "fixture-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in manifest.items() if k != "commands"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
