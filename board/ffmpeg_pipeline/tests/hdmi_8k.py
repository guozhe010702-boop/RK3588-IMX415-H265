#!/usr/bin/env python3
"""Attach VPU decode/RGA/HDMI to the existing real-camera 8K30 RTSP publisher.

Does not open a camera, restart the encoder or alter display modes. Close the
HDMI window, create OUTPUT/stop.request, or stop the source to end this branch.
"""
import argparse
import csv
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
URL = "rtsp://127.0.0.1:8555/imx415-upscaled-8k30"
sys.path.insert(0, str(ROOT))
from camera_control.decoder import HardwareDisplay
from camera_control.metrics import Rates, memory_usage, proc_usage, read_number
from camera_control.support import atomic_json, mpp_device_open, tail


class Host:
    def __init__(self, output):
        self.root = output
        (output / "logs").mkdir(exist_ok=True)
        self.ffmpeg = str(ROOT / "runtime/bin/ffmpeg")
        self.environment = dict(
            os.environ,
            LD_LIBRARY_PATH=str(ROOT / "runtime/lib") + ":" + str(ROOT / "runtime/lib64"),
        )
        self.environment.pop("LD_PRELOAD", None)
        self.config = {"width": 7680, "height": 4320, "fps": 30, "codec": "h265"}

    @staticmethod
    def active(process):
        return process is not None and process.poll() is None

    @staticmethod
    def stop_child(process, timeout=3):
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def find_capture():
    """Match the lab's saved exact FFmpeg command to a live process, no PID guesses."""
    commands = {}
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            args = [x.decode() for x in (proc / "cmdline").read_bytes().split(b"\0") if x]
            if "/dev/video44" in args and "hevc_rkmpp" in args and any(URL in arg for arg in args):
                commands[tuple(args)] = int(proc.name)
        except (OSError, UnicodeError):
            pass
    for file in sorted(
        (ROOT / "lab8k-camera").glob("*/evidence/command.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        try:
            pid = commands.get(tuple(json.loads(file.read_text())))
            if pid:
                return pid, file.parent
        except (OSError, ValueError):
            pass
    raise RuntimeError("No matching live IMX415 8K30 lab encoder; start it first")


def capture_progress(folder):
    for line in reversed(tail(folder / "progress.jsonl", 8)):
        try:
            return json.loads(line)
        except ValueError:
            pass
    return {}


def temperatures():
    values = []
    for file in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        value = read_number(file)
        if value is not None:
            values.append(value / 1000)
    return max(values) if values else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--seconds", type=int, default=0, help="0 keeps HDMI running until stopped")
    a = p.parse_args()
    if not 0 <= a.seconds <= 3600:
        p.error("seconds must be 0..3600")
    a.output.mkdir(parents=True, exist_ok=True)
    if any(a.output.iterdir()):
        raise RuntimeError("Use a new empty output directory")
    (ROOT / "state").mkdir(exist_ok=True)
    lock = (ROOT / "state/hdmi-8k.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not any(
        p.read_text().strip() == "connected"
        for p in Path("/sys/class/drm").glob("card*-HDMI*/status")
    ):
        raise RuntimeError("No connected HDMI display")
    capture_pid, capture_folder = find_capture()
    host = Host(a.output)
    probe = subprocess.check_output(
        [
            str(ROOT / "runtime/bin/ffprobe"),
            "-v",
            "error",
            "-rtsp_transport",
            "tcp",
            "-timeout",
            "5000000",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            URL,
        ],
        env=host.environment,
        timeout=10,
    )
    stream = json.loads(probe)["streams"][0]
    if (stream["codec_name"], stream["width"], stream["height"], stream["r_frame_rate"]) != (
        "hevc",
        7680,
        4320,
        "30/1",
    ):
        raise RuntimeError("Requires real-camera lab HEVC 7680x4320 30 fps")
    display = HardwareDisplay(host, source_url=URL, timestamped=True, fullscreen=True)
    rates, start = Rates(), time.monotonic()
    before = capture_progress(capture_folder)
    result = {
        "scope": "IMX415_REAL_8K30_PARALLEL_VPU_HDMI",
        "native8k": False,
        "workerPid": os.getpid(),
        "source": URL,
        "sourceProbe": stream,
        "capturePid": capture_pid,
        "captureEvidence": str(capture_folder),
        "captureBefore": before,
        "display": None,
        "stopReason": None,
    }
    stopping = [False]
    signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__(0, True))
    signal.signal(signal.SIGINT, lambda *_: stopping.__setitem__(0, True))
    records = []
    try:
        display.start()
        result["decoderPid"] = display.process.pid
        result["playerPid"] = display.player.pid
        with (a.output / "samples.jsonl").open("w", buffering=1) as samples, (
            a.output / "metrics.csv"
        ).open("w", newline="") as csvfile:
            writer = None
            while True:
                now = time.monotonic()
                view = display.snapshot()
                progress = capture_progress(capture_folder)
                encoded = rates.delta(
                    "encode", capture_pid, progress.get("frame"), progress.get("monotonic_s", 0)
                )
                resources = {}
                for name, pid in (
                    ("encoder", capture_pid),
                    ("decoder", result["decoderPid"]),
                    ("player", result["playerPid"]),
                ):
                    usage = proc_usage(pid)
                    if usage:
                        cpu = rates.delta("cpu:" + name, (pid, usage[0]), usage[1], now)
                        resources[name] = {
                            "pid": pid,
                            "cpuOneCorePercent": cpu * 100 if cpu is not None else None,
                            "rssMiB": usage[2] / 1048576,
                        }
                sample = {
                    "elapsed": now - start,
                    "at": datetime.datetime.now().astimezone().isoformat(),
                    "encodeFrames": progress.get("frame"),
                    "encodeFps": encoded,
                    "encoderVpuOpen": mpp_device_open(capture_pid),
                    "display": view,
                    "memory": memory_usage(Path("/proc/meminfo").read_text()),
                    "temperatureMaxC": temperatures(),
                    "processes": resources,
                }
                atomic_json(a.output / "status.json", sample)
                samples.write(json.dumps(sample) + "\n")
                records.append(
                    {
                        "elapsed": now - start,
                        "encodeFrames": progress.get("frame"),
                        "decodeFrames": view["frame"],
                        "decoderVpuOpen": view["vpuDeviceOpen"],
                        "encoderVpuOpen": sample["encoderVpuOpen"],
                        "frameAge": view["lastFrameAgeSeconds"],
                    }
                )
                row = {
                    "seconds": round(now - start, 3),
                    "encodeFrames": progress.get("frame"),
                    "encodeFps": encoded,
                    "decodeFrames": view["frame"],
                    "decodeFps": view["intervalFps"],
                    "temperatureMaxC": sample["temperatureMaxC"],
                    "memoryPercent": sample["memory"].get("percent"),
                }
                for name in ("encoder", "decoder", "player"):
                    resource = resources.get(name, {"cpuOneCorePercent": None, "rssMiB": None})
                    row[name + "CpuOneCorePercent"] = resource["cpuOneCorePercent"]
                    row[name + "RssMiB"] = resource["rssMiB"]
                if writer is None:
                    writer = csv.DictWriter(csvfile, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                csvfile.flush()
                if stopping[0] or (a.output / "stop.request").exists():
                    result["stopReason"] = "requested"
                    break
                if a.seconds and now - start >= a.seconds:
                    result["stopReason"] = "duration-complete"
                    break
                if not view["running"]:
                    result["stopReason"] = "display-exited"
                    break
                if (
                    not Path("/proc/{}/cmdline".format(capture_pid)).exists()
                    or (capture_folder / "result.json").exists()
                ):
                    result["stopReason"] = "source-ended"
                    break
                if now - start > 15 and view["lastFrameAgeSeconds"] > 5:
                    raise RuntimeError("HDMI decoder frames stalled")
                time.sleep(1)
    finally:
        result["display"] = display.snapshot()
        result["captureAfter"] = capture_progress(capture_folder)
        result["seconds"] = time.monotonic() - start
        steady = [r for r in records if r["elapsed"] >= 10]
        if len(steady) >= 2:
            dt = steady[-1]["elapsed"] - steady[0]["elapsed"]
            result["steadyEncodeFps"] = (
                steady[-1]["encodeFrames"] - steady[0]["encodeFrames"]
            ) / dt
            result["steadyDecodeFps"] = (
                steady[-1]["decodeFrames"] - steady[0]["decodeFrames"]
            ) / dt
            result["steadyVpuObserved"] = all(
                r["decoderVpuOpen"] and r["encoderVpuOpen"] for r in steady
            )
        decoder, player = display.process, display.player
        display.stop()
        result["decoderExitCode"] = decoder.returncode if decoder else None
        result["playerExitCode"] = player.returncode if player else None
        atomic_json(a.output / "result.json", result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
