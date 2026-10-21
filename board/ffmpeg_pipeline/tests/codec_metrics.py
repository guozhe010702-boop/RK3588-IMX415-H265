"""Shared codec lab process/measurement helpers. This module supplies no video input."""

import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def camera_owners():
    owners = []
    for process in Path("/proc").glob("[0-9]*"):
        for fd in (process / "fd").glob("*"):
            try:
                if os.readlink(str(fd)) == "/dev/video44":
                    owners.append(int(process.name))
                    break
            except OSError:
                pass
    return owners


def throughput(samples):
    if len(samples) < 2:
        return None
    # Exclude the startup baseline; use actual count / monotonic interval, not fps metadata.
    first, last = samples[0], samples[-1]
    delta = last["monotonic_s"] - first["monotonic_s"]
    return (last["frame"] - first["frame"]) / delta if delta > 0 else None


def frame_errors(log):
    return [
        line
        for line in log.splitlines()
        if re.search(
            r"Error (while|submitting|sending|during|decoding)|corrupt|Invalid data|Failed to (decode|encode)|failed to.*frame|no frame!",
            line,
            re.I,
        )
    ]


def execute(ffmpeg, env, args, output, frames):
    started = time.monotonic()
    mpp = False
    samples = []
    buffer = ""
    record = {}
    logpath = output / "ffmpeg.log"
    progresspath = output / "progress.jsonl"
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "info",
        "-stats_period",
        "1",
        "-progress",
        "pipe:1",
    ] + args
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    with logpath.open("w") as log, progresspath.open("w") as progress:
        child = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=log,
            start_new_session=True,
        )
        os.set_blocking(child.stdout.fileno(), False)
        try:
            while True:
                readable, _, _ = select.select([child.stdout], [], [], 0.1)
                if readable:
                    chunk = os.read(child.stdout.fileno(), 65536)
                    if not chunk and child.poll() is not None:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        record[key] = value
                        if key == "progress":
                            sample = {
                                "monotonic_s": time.monotonic() - started,
                                "frame": int(record.get("frame", 0)),
                                "duplicate_frames": int(record.get("dup_frames", 0)),
                                "dropped_frames": int(record.get("drop_frames", 0)),
                                "out_time_us": record.get("out_time_us"),
                            }
                            samples.append(sample)
                            progress.write(json.dumps(sample) + "\n")
                            progress.flush()
                            record = {}
                for fd in Path("/proc", str(child.pid), "fd").glob("*"):
                    try:
                        mpp |= os.readlink(str(fd)) in (
                            "/dev/mpp_service",
                            "/dev/mpp-service",
                            "/dev/rkvenc",
                            "/dev/rkvdec",
                        )
                    except OSError:
                        pass
                if time.monotonic() - started > 180:
                    raise TimeoutError("codec lab exceeded 180 seconds")
                if child.poll() is not None and not readable:
                    break
            child.wait(timeout=5)
        finally:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            child.stdout.close()
    elapsed = time.monotonic() - started
    count = samples[-1]["frame"] if samples else 0
    return {
        "exitCode": child.returncode,
        "frames": count,
        "wallSeconds": elapsed,
        "wholeRunFps": count / elapsed,
        "intervalFps": throughput(samples),
        "intervalSeconds": (
            samples[-1]["monotonic_s"] - samples[0]["monotonic_s"] if len(samples) > 1 else 0
        ),
        "mppDeviceObserved": mpp,
        "expectedFrames": frames,
        "duplicateFrames": samples[-1]["duplicate_frames"] if samples else None,
        "droppedFrames": samples[-1]["dropped_frames"] if samples else None,
    }
