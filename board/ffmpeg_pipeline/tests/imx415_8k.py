#!/usr/bin/env python3
"""Real IMX415 camera lab: spatially upscaled 8K30 encode, or real 4K60 source.

Never generates patterns, interpolates or repeats frames. Native sensor capture
stays at 3840x2160. Decoder inputs require the camera-source manifest.
"""
import argparse
from fractions import Fraction
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from codec_metrics import ROOT, camera_owners, execute, frame_errors


def capture_arguments(mode, source_fps, frames, movie, rtsp=False, live=False):
    if mode not in ("encode30", "capture60"):
        raise ValueError("Not a real-camera capture mode")
    if live and (mode != "encode30" or not rtsp):
        raise ValueError("Live preview requires encode30 and RTSP")
    target = 30 if mode == "encode30" else 60
    ratio = source_fps / target
    if ratio < 1 or abs(ratio - round(ratio)) > 0.01:
        raise ValueError("Sensor fps must be an integer multiple of output fps; no duplication")
    filters = ["trim=start_frame=5"]
    if round(ratio) > 1:
        filters.append("select=not(mod(n\\,{}))".format(round(ratio)))
    # Vendor restart timestamps can jump. Select actual frames, then rebase PTS.
    # Actual wall-clock capture/encode rates remain independently measured.
    filters.append("setpts=N/({}*TB)".format(target))
    if round(ratio) > 1:
        # The select filter keeps the input's declared fps. Normalize the
        # already uniform selected timestamps so HEVC VUI/RTSP also say 30.
        # Verbose filter counters below must confirm zero repeated frames.
        filters.append("fps=fps={}:round=near:eof_action=pass".format(target))
    if mode == "encode30":
        filters += ["hwupload", "scale_rkrga=w=7680:h=4320:format=nv12"]
    args = [
        "-init_hw_device",
        "rkmpp=rk",
        "-filter_hw_device",
        "rk",
        "-f",
        "v4l2",
        "-capture_buffers",
        "16",
        "-input_format",
        "nv12",
        "-video_size",
        "3840x2160",
        "-framerate",
        str(source_fps),
        "-i",
        "/dev/video44",
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        ",".join(filters),
        "-c:v",
        "hevc_rkmpp",
        "-rc_mode",
        "CBR",
        "-b:v",
        "60000000",
        "-maxrate",
        "60000000",
        "-g",
        str(target),
        "-bf",
        "0",
        "-fps_mode",
        "passthrough",
    ]
    if live:
        return args + [
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            "rtsp://127.0.0.1:8555/imx415-upscaled-8k30",
        ]
    args += ["-frames:v", str(frames)]
    if rtsp:
        return args + [
            "-flags",
            "+global_header",
            "-f",
            "tee",
            "[f=mp4:movflags=+faststart]{}|[f=rtsp:rtsp_transport=tcp]"
            "rtsp://127.0.0.1:8555/imx415-upscaled-8k30".format(movie),
        ]
    return args + ["-tag:v", "hvc1", "-n", str(movie)]


def probe(ffprobe, env, source):
    value = subprocess.check_output(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            str(source),
        ],
        env=env,
        timeout=20,
    )
    return json.loads(value)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("encode30", "capture60", "decode60"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--input", type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--frames", type=int, default=600)
    p.add_argument("--rtsp", action="store_true", help="owned port 8555 server, encode30 only")
    p.add_argument("--display-scale", action="store_true")
    p.add_argument("--handover", action="store_true")
    p.add_argument(
        "--live", action="store_true", help="continuous RTSP only; no MP4, no frame limit"
    )
    a = p.parse_args()
    if not 120 <= a.frames <= 3600:
        p.error("frames must be 120..3600")
    if a.rtsp and a.mode != "encode30":
        p.error("RTSP applies to encode30 only")
    if a.display_scale and a.mode != "decode60":
        p.error("display-scale applies to decode60 only")
    if a.live and (a.mode != "encode30" or not a.rtsp):
        p.error("--live requires --mode encode30 --rtsp")
    import fcntl

    sys.path.insert(0, str(ROOT))
    from camera_control.support import camera_capabilities, sensor_frame_rate
    from camera_control.transport import request

    env = dict(
        os.environ, LD_LIBRARY_PATH=str(ROOT / "runtime/lib") + ":" + str(ROOT / "runtime/lib64")
    )
    env.pop("LD_PRELOAD", None)
    ffmpeg, ffprobe = [str(ROOT / ("runtime/bin/" + name)) for name in ("ffmpeg", "ffprobe")]
    a.output.mkdir(parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        raise RuntimeError("Use a new empty output directory")
    (ROOT / "state").mkdir(exist_ok=True)
    with (ROOT / "state/codec-lab.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        response = request("status", {})
        if not response.get("ok"):
            raise RuntimeError(str(response))
        saved = response["result"]
        if saved.get("recording"):
            raise RuntimeError("Finalize the current recording first")
        if saved.get("capturePid") and not a.handover:
            raise RuntimeError("Live capture is active; explicit --handover is required")
        if not saved.get("capturePid") and camera_owners():
            raise RuntimeError("Unknown camera owner; no process will be killed")
        result = {
            "scope": "IMX415_REAL_CAMERA_SPATIALLY_UPSCALED",
            "native8k": False,
            "mode": a.mode,
            "sourceSize": [3840, 2160],
            "restored": False,
            "livePreview": a.live,
            "recording": a.mode != "decode60" and not a.live,
        }
        movie = a.output / (
            "camera-upscaled-8k30.mp4" if a.mode == "encode30" else "camera-4k60.mp4"
        )
        if a.mode != "decode60":
            capability = camera_capabilities("/dev/video44")
            if "imx415" not in capability.get("sensorName", "").lower():
                raise RuntimeError("Connected sensor is not identified as IMX415")
            fps = sensor_frame_rate("/dev/video44")
            if fps is None:
                raise RuntimeError("Cannot verify sensor frame interval")
            args = capture_arguments(a.mode, fps, a.frames, movie, a.rtsp, a.live)
            result.update(
                sensor=capability,
                sensorReportedFps=fps,
                outputSize=[7680, 4320] if a.mode == "encode30" else [3840, 2160],
                outputFps=30 if a.mode == "encode30" else 60,
                timestampPolicy="discard first 5; select real frames; rebase PTS; no duplication",
            )
            if a.mode == "capture60":
                result["scope"] = "IMX415_REAL_CAMERA_4K60_CAPTURE"
        else:
            if not a.input or not a.manifest:
                raise RuntimeError("Decoder requires --input and camera-source --manifest")
            provenance = json.loads(a.manifest.read_text())
            import hashlib

            digest = hashlib.sha256(a.input.read_bytes()).hexdigest()
            if (
                provenance.get("scope") != "IMX415_REAL_4K60_OFFLINE_SPATIAL_UPSCALE_8K60"
                or provenance.get("sha256") != digest
            ):
                raise RuntimeError("Unverified camera-source file or manifest")
            info = probe(ffprobe, env, a.input)["streams"][0]
            if (
                info["codec_name"],
                info["width"],
                info["height"],
                Fraction(info["r_frame_rate"]),
            ) != ("hevc", 7680, 4320, 60):
                raise RuntimeError("Requires an actual HEVC 7680x4320 60 fps file")
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
                str(a.input),
                "-map",
                "0:v:0",
                "-an",
                "-frames:v",
                str(a.frames),
            ]
            if a.display_scale:
                args += ["-vf", "scale_rkrga=w=1920:h=1080:format=nv12,hwdownload,format=nv12"]
            args += ["-fps_mode", "passthrough", "-f", "null", "-"]
            result.update(
                provenance=provenance,
                scope="IMX415_REAL_4K60_OFFLINE_SPATIAL_UPSCALE_8K60_DECODE",
                decodeSize=[7680, 4320],
                outputFps=60,
                displaySize=[1920, 1080] if a.display_scale else None,
                playback="unpaced file loop; decoder throughput, not live camera latency",
            )
        stopped, server = False, None
        (a.output / "before.json").write_text(json.dumps(saved, indent=2))
        try:
            if saved.get("capturePid"):
                response = request("stop", {})
                if not response.get("ok"):
                    raise RuntimeError(str(response))
                stopped = True
            if camera_owners():
                raise RuntimeError("Camera remains occupied; refused")
            if a.rtsp:
                with (a.output / "mediamtx.log").open("w") as log:
                    server = subprocess.Popen(
                        [
                            str(ROOT / "runtime/bin/mediamtx"),
                            str(ROOT / "profiles/8k/mediamtx.yml"),
                        ],
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                time.sleep(0.6)
                if server.poll() is not None:
                    raise RuntimeError("Port 8555 server failed; see mediamtx.log")
            result["measurement"] = m = execute(
                ffmpeg,
                env,
                ["-loglevel", "verbose"] + args,
                a.output,
                0 if a.live else a.frames,
                timeout_seconds=None if a.live else 180,
                stop_file=a.output / "stop.request" if a.live else None,
            )
            log = (a.output / "ffmpeg.log").read_text(errors="replace")
            result["frameErrorLines"] = frame_errors(log)
            import re

            repeats = re.findall(r"(\d+) frames duplicated", log)
            result["filterDuplicateFrames"] = sum(map(int, repeats)) if repeats else None

            result["captureSamples"] = [
                dict((k, int(v)) for k, v in re.findall(r"(\w+)=(\d+)", line))
                for line in log.splitlines()
                if "AV_CAPTURE frames=" in line
            ]
            stable = result["captureSamples"][1:]
            if len(stable) >= 2 and stable[-1]["mono_us"] > stable[0]["mono_us"]:
                result["captureIntervalFps"] = (
                    (stable[-1]["frames"] - stable[0]["frames"])
                    * 1e6
                    / (stable[-1]["mono_us"] - stable[0]["mono_us"])
                )
                result["captureIntervalGaps"] = stable[-1]["gaps"] - stable[0]["gaps"]
            valid = True
            if a.mode != "decode60" and not a.live and m["exitCode"] == 0:
                result["encodedProbe"] = info = probe(ffprobe, env, movie)
                stream = info["streams"][0]
                valid = (
                    stream["width"],
                    stream["height"],
                    Fraction(stream["r_frame_rate"]),
                    int(stream.get("nb_frames", 0)),
                ) == (*result["outputSize"], result["outputFps"], a.frames)
                import hashlib

                result["fileSha256"] = hashlib.sha256(movie.read_bytes()).hexdigest()
            result["shortTestPassed"] = bool(
                not a.live
                and valid
                and m["exitCode"] == 0
                and m["frames"] == a.frames
                and m["mppDeviceObserved"]
                and m["intervalSeconds"] >= 5
                and (m["intervalFps"] or 0) >= result["outputFps"] * 0.98
                and m["duplicateFrames"] == 0
                and m["droppedFrames"] == 0
                and (
                    a.mode != "encode30"
                    or result["sensorReportedFps"] == 30
                    or result["filterDuplicateFrames"] == 0
                )
                and not result["frameErrorLines"]
            )
            result["livePreviewEnded"] = bool(
                a.live
                and m["stopRequested"]
                and m["exitCode"] in (0, 255)
                and m["frames"] > 0
                and m["mppDeviceObserved"]
                and not result["frameErrorLines"]
            )
        finally:
            if server is not None and server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            try:
                if stopped:
                    restored = request("start", {"config": saved["config"]})
                    if not restored.get("ok"):
                        raise RuntimeError("Original stream restore failed: " + str(restored))
                    if saved.get("previewRunning"):
                        restored = request("decode-start", {})
                        if not restored.get("ok"):
                            raise RuntimeError("HDMI restore failed: " + str(restored))
            except Exception as error:
                result["restoreError"] = str(error)
            actual = request("status", {}).get("result", {})
            result["restored"] = not stopped or bool(
                actual.get("capturePid")
                and actual.get("config") == saved.get("config")
                and (not saved.get("previewRunning") or actual.get("previewRunning"))
            )
            if result.get("restoreError"):
                result["restored"] = False
            (a.output / "after.json").write_text(json.dumps(actual, indent=2))
            temporary = a.output / "result.tmp.json"
            temporary.write_text(json.dumps(result, indent=2))
            temporary.replace(a.output / "result.json")
        print(json.dumps(result, indent=2), flush=True)
        return (
            0
            if (result.get("shortTestPassed") or result.get("livePreviewEnded"))
            and result.get("restored")
            else 1
        )


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    sys.exit(main())
