#!/usr/bin/env python3
"""RK3588 synthetic 8K30 encode / 8K30,60 decode lab. Never camera acceptance.

No encode60 mode: RK3588's specified 8K60 capability is decoding. Test input
must be complete 7680x4320 data. Nothing is upscaled or interpolated here.
"""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time

from codec_metrics import ROOT, camera_owners, execute, frame_errors, throughput

W, H = 7680, 4320
FRAME_BYTES = W * H * 3 // 2
MODES = ("encode30", "decode30", "decode60")


def arguments(mode, source, movie, frames, bitrate, display_scale=False):
    if mode not in MODES:
        raise ValueError("8K60 encoding is not supported by the RK3588 specification")
    if mode == "encode30":
        return [
            "-stream_loop",
            "-1",
            "-f",
            "rawvideo",
            "-pixel_format",
            "nv12",
            "-video_size",
            "7680x4320",
            "-framerate",
            "30",
            "-i",
            str(source),
            "-an",
            "-frames:v",
            str(frames),
            "-c:v",
            "hevc_rkmpp",
            "-rc_mode",
            "CBR",
            "-b:v",
            str(bitrate),
            "-g",
            "30",
            "-bf",
            "0",
            "-fps_mode",
            "passthrough",
            "-tag:v",
            "hvc1",
            "-n",
            str(movie),
        ]
    args = [
        "-hwaccel",
        "rkmpp",
        "-hwaccel_output_format",
        "drm_prime",
        "-c:v",
        "hevc_rkmpp",
        "-stream_loop",
        "-1",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-an",
        "-frames:v",
        str(frames),
    ]
    if display_scale:
        args += ["-vf", "scale_rkrga=w=1920:h=1080:format=nv12,hwdownload,format=nv12"]
    return args + ["-fps_mode", "passthrough", "-f", "null", "-"]


def run(args):
    import fcntl

    sys.path.insert(0, str(ROOT))
    from camera_control.transport import request

    saved = request("status", {}).get("result", {})
    if saved.get("recording"):
        raise RuntimeError("Recording active; stop/finalize it before running the codec lab")
    was_running = bool(saved.get("capturePid"))
    if was_running and not args.handover:
        raise RuntimeError("Capture is running; use --handover for explicit temporary stop/restore")
    # The lab never touches /dev/video*: unknown camera owners are left alone.
    if not was_running:
        busy = camera_owners()
        if busy:
            raise RuntimeError(
                "Another camera process is active; refusing a competing performance test"
            )
    ffmpeg = str(ROOT / "runtime/bin/ffmpeg")
    ffprobe = str(ROOT / "runtime/bin/ffprobe")
    env = dict(
        os.environ, LD_LIBRARY_PATH=str(ROOT / "runtime/lib") + ":" + str(ROOT / "runtime/lib64")
    )
    env.pop("LD_PRELOAD", None)
    source = args.input.resolve()
    if args.mode == "encode30":
        if (
            not source.is_file()
            or source.stat().st_size < FRAME_BYTES
            or source.stat().st_size % FRAME_BYTES
        ):
            raise RuntimeError("Input must contain complete, tightly packed 7680x4320 NV12 frames")
    else:
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,r_frame_rate",
                "-of",
                "json",
                str(source),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        if (stream["codec_name"], stream["width"], stream["height"]) != ("hevc", W, H):
            raise RuntimeError("Decoder test requires an actual 7680x4320 HEVC bitstream")
        if Fraction(stream["r_frame_rate"]) != int(args.mode[-2:]):
            raise RuntimeError("Input fps does not match the requested decoder test mode")
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise RuntimeError("Use a new empty output directory; old evidence is never overwritten")
    state = ROOT / "state"
    state.mkdir(exist_ok=True)
    with (state / "codec-lab.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (args.output / "before.json").write_text(json.dumps(saved, indent=2) + "\n")
        result = {
            "scope": "SYNTHETIC_CODEC_ONLY",
            "real8kCameraValidated": False,
            "mode": args.mode,
            "decodeSize": [W, H] if args.mode != "encode30" else None,
            "scaledOutputSize": [1920, 1080] if args.display_scale else None,
            "targetFps": int(args.mode[-2:]),
            "input": str(source),
            "restored": False,
        }
        stopped = False
        try:
            if was_running:
                response = request("stop", {})
                if not response.get("ok"):
                    raise RuntimeError(str(response))
                stopped = True
            cmd = arguments(
                args.mode,
                source,
                args.output / "encoded-8k30.mp4",
                args.frames,
                args.bitrate,
                args.display_scale,
            )
            result["measurement"] = execute(ffmpeg, env, cmd, args.output, args.frames)
            m = result["measurement"]
            result["frameErrorLines"] = frame_errors(
                (args.output / "ffmpeg.log").read_text(errors="replace")
            )
            format_valid = True
            if args.mode == "encode30" and m["exitCode"] == 0:
                probe = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-select_streams",
                        "v:0",
                        "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,nb_frames",
                        "-of",
                        "json",
                        str(args.output / "encoded-8k30.mp4"),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=True,
                )
                result["encodedStream"] = stream = json.loads(probe.stdout)["streams"][0]
                format_valid = (
                    stream["codec_name"] == "hevc"
                    and stream["width"] == W
                    and stream["height"] == H
                    and Fraction(stream["r_frame_rate"]) == 30
                    and int(stream.get("nb_frames", 0)) == args.frames
                )
            result["patternThroughputPassed"] = bool(
                m["exitCode"] == 0
                and m["frames"] == args.frames
                and m["mppDeviceObserved"]
                and m["intervalFps"] is not None
                and m["intervalFps"] >= result["targetFps"] * 0.98
                and m["intervalSeconds"] >= 5
                and m["duplicateFrames"] == 0
                and m["droppedFrames"] == 0
                and not result["frameErrorLines"]
                and format_valid
            )
        finally:
            if stopped:
                restored = request("start", {"config": saved["config"]})
                if not restored.get("ok"):
                    raise RuntimeError("Original stream restore failed: " + str(restored))
                if saved.get("previewRunning"):
                    preview = request("decode-start", {})
                    if not preview.get("ok"):
                        raise RuntimeError("HDMI restore failed: " + str(preview))
            actual = request("status", {}).get("result", {})
            result["restored"] = not stopped or bool(
                actual.get("capturePid") and actual.get("config") == saved.get("config")
            )
            (args.output / "after.json").write_text(json.dumps(actual, indent=2) + "\n")
            (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result.get("measurement", {}).get("exitCode") == 0 else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=MODES, required=True)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--frames", type=int, default=600)
    p.add_argument("--bitrate", type=int, default=60000000)
    p.add_argument(
        "--display-scale",
        action="store_true",
        help="include RGA 1080p conversion, no physical display",
    )
    p.add_argument("--handover", action="store_true")
    a = p.parse_args()
    if not 120 <= a.frames <= 3600 or not 1000000 <= a.bitrate <= 100000000:
        p.error("frames 120..3600 and bitrate 1..100 Mbit/s required")
    if a.mode == "encode30" and a.display_scale:
        p.error("display scale only applies to decoder tests")
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    sys.exit(run(a))


if __name__ == "__main__":
    main()
