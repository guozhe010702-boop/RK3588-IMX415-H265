"""Spatially upscale a verified IMX415 4K60 recording to an offline 8K60 HEVC file.

No synthetic input, temporal interpolation, frame repetition or fps rewriting.
PC software encoding is deliberately offline; this is not RK3588 8K60 encoding.
"""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def arguments(source, output, frames):
    return [
        "-hide_banner",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-frames:v",
        str(frames),
        "-vf",
        "scale=7680:4320:flags=bilinear",
        "-c:v",
        "libx265",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-x265-params",
        "pools=4:frame-threads=1:wpp=1:bframes=0:ref=1:rc-lookahead=0:keyint=60:min-keyint=60:scenecut=0",
        "-fps_mode",
        "passthrough",
        "-tag:v",
        "hvc1",
        "-n",
        str(output),
    ]


def probe(ffprobe, source):
    return json.loads(
        subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,nb_frames:packet=pts_time,dts_time",
                "-show_packets",
                "-of",
                "json",
                str(source),
            ],
            timeout=30,
        )
    )


def validate_camera(source, evidence, info):
    m = evidence.get("measurement", {})
    if (
        evidence.get("scope") != "IMX415_REAL_CAMERA_4K60_CAPTURE"
        or evidence.get("mode") != "capture60"
        or not evidence.get("shortTestPassed")
        or evidence.get("fileSha256") != hashlib.sha256(source.read_bytes()).hexdigest()
        or evidence.get("captureIntervalFps", 0) < 59
        or (m.get("intervalFps") or 0) < 59
    ):
        raise ValueError("Not a verified real IMX415 4K60 recording; no fake-60 conversion allowed")
    stream = info["streams"][0]
    if (stream["width"], stream["height"], Fraction(stream["r_frame_rate"])) != (3840, 2160, 60):
        raise ValueError("Input must already be 3840x2160 60 fps")
    pts = [Fraction(packet["pts_time"]) for packet in info["packets"]]
    if len(pts) != int(stream["nb_frames"]) or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError("Input packet count/timestamps invalid")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True, help="capture60 result.json")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--frames", type=int, default=120)
    a = p.parse_args()
    if not 120 <= a.frames <= 600:
        p.error("frames 120..600 required")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("PC FFmpeg with libx265 and ffprobe must be in PATH")
    evidence = json.loads(a.evidence.read_text(encoding="utf-8"))
    info = probe(ffprobe, a.input)
    validate_camera(a.input, evidence, info)
    if int(info["streams"][0]["nb_frames"]) < a.frames:
        raise ValueError("Input has fewer frames than requested")
    a.output.mkdir(parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        raise RuntimeError("Use a new empty output directory")
    movie = a.output / "camera-upscaled-8k60.mp4"
    command = [ffmpeg] + arguments(a.input, movie, a.frames)
    (a.output / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    print(
        "Offline PC spatial upscale/encode; frame count and source 60 fps are preserved.",
        flush=True,
    )
    with (a.output / "ffmpeg.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=log, check=True, timeout=1800)
    actual = probe(ffprobe, movie)
    stream = actual["streams"][0]
    if (
        stream["codec_name"],
        stream["width"],
        stream["height"],
        Fraction(stream["r_frame_rate"]),
        int(stream["nb_frames"]),
    ) != ("hevc", 7680, 4320, 60, a.frames):
        raise RuntimeError("Output size/fps/frame count mismatch")
    pts = [Fraction(packet["pts_time"]) for packet in actual["packets"]]
    source_pts = [Fraction(packet["pts_time"]) for packet in info["packets"][: a.frames]]
    if len(pts) != a.frames or any(
        abs((b - pts[0]) - (a - source_pts[0])) > Fraction(1, 10000)
        for a, b in zip(source_pts, pts)
    ):
        raise RuntimeError("Source timestamps were not preserved")
    manifest = {
        "scope": "IMX415_REAL_4K60_OFFLINE_SPATIAL_UPSCALE_8K60",
        "native8k": False,
        "realCamera": True,
        "temporalInterpolation": False,
        "offlineEncoding": True,
        "sourceSha256": evidence["fileSha256"],
        "sourceSize": [3840, 2160],
        "sourceFps": 60,
        "outputSize": [7680, 4320],
        "outputFps": 60,
        "frames": a.frames,
        "sha256": hashlib.sha256(movie.read_bytes()).hexdigest(),
        "captureIntervalFps": evidence["captureIntervalFps"],
        "captureIntervalGaps": evidence.get("captureIntervalGaps"),
        "command": command,
        "outputProbe": stream,
    }
    (a.output / "camera-source.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
