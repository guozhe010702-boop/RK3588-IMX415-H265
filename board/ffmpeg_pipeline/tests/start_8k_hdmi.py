#!/usr/bin/env python3
"""One-command real IMX415 4K -> upscaled 8K30 encode -> VPU decode -> HDMI.

Reuses an existing matching lab encoder. Only a source started by this command
is stopped on exit. No PC decoder, recording or synthetic video is involved.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


class StopRequested(Exception):
    pass


def discover_capture():
    # Import lazily: the HDMI runtime uses Linux-only fcntl.
    from hdmi_8k import find_capture

    try:
        return find_capture()
    except RuntimeError as error:
        if str(error).startswith("No matching live IMX415"):
            return None
        raise


def source_command(output, handover=False):
    args = [
        sys.executable,
        str(ROOT / "tests/imx415_8k.py"),
        "--mode",
        "encode30",
        "--rtsp",
        "--live",
        "--output",
        str(output / "evidence"),
    ]
    if handover:
        args.append("--handover")
    return args


def hdmi_command(output, seconds=0):
    return [
        sys.executable,
        str(ROOT / "tests/hdmi_8k.py"),
        "--output",
        str(output / "hdmi"),
        "--seconds",
        str(seconds),
    ]


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def stop_owned(process, stop_file):
    if process is None or process.poll() is not None:
        return
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.touch()
    try:
        process.wait(timeout=35)
    except subprocess.TimeoutExpired:
        process.terminate()
        # Do not kill a worker halfway through restoration of an older stream.
        process.wait(timeout=30)


def wait_source(process, output, stopping, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stopping[0]:
            raise StopRequested()
        if process.poll() is not None:
            raise RuntimeError("编码源启动失败，请查看 " + str(output / "source-worker.log"))
        capture = discover_capture()
        if capture:
            progress = capture[1] / "progress.jsonl"
            if progress.is_file():
                for line in reversed(progress.read_text().splitlines()[-3:]):
                    try:
                        if json.loads(line).get("frame", 0) > 0:
                            return capture
                    except ValueError:
                        pass
        time.sleep(0.25)
    raise RuntimeError("等待 8K30 编码出帧超时，请查看 " + str(output / "source-worker.log"))


def run(output, seconds, handover, stopping):
    output.mkdir(parents=True, exist_ok=False)
    (ROOT / "state").mkdir(exist_ok=True)
    source = hdmi = None
    logs = []
    session = {
        "scope": "IMX415_REAL_CAMERA_UPSCALED_8K30_STANDALONE_HDMI",
        "native8k": False,
        "workerPid": os.getpid(),
        "ownsSource": False,
        "sourceSize": [3840, 2160],
        "encodedSize": [7680, 4320],
        "output": str(output),
    }
    try:
        capture = discover_capture()
        if capture is None:
            print("未发现编码源，正在启动 IMX415 实拍 → RGA 放大 → VPU 8K30 硬编。", flush=True)
            log = (output / "source-worker.log").open("wb")
            logs.append(log)
            source = subprocess.Popen(
                source_command(output, handover),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            session.update(ownsSource=True, sourceWorkerPid=source.pid)
            write_json(output / "session.json", session)
            capture = wait_source(source, output, stopping)
        else:
            print("复用已有实拍 8K30 编码源；退出时保留该源。", flush=True)
        session.update(capturePid=capture[0], captureEvidence=str(capture[1]))
        if stopping[0]:
            raise StopRequested()
        log = (output / "hdmi-worker.log").open("wb")
        logs.append(log)
        hdmi = subprocess.Popen(
            hdmi_command(output, seconds),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        session["hdmiWorkerPid"] = hdmi.pid
        write_json(output / "session.json", session)
        write_json(
            ROOT / "state/hdmi-8k-active.json",
            {"pid": hdmi.pid, "output": str(output / "hdmi"), "tag": output.name},
        )
        print("正在启动 VPU 完整硬解 8K → RGA 缩放 → HDMI。日志：" + str(output), flush=True)
        announced = False
        while hdmi.poll() is None:
            if stopping[0]:
                raise StopRequested()
            if source is not None and source.poll() is not None:
                raise RuntimeError("本次编码源已退出，请查看 " + str(output / "source-worker.log"))
            status = output / "hdmi/status.json"
            if not announced and status.exists():
                view = json.loads(status.read_text()).get("display", {})
                if view.get("frame", 0) > 0:
                    print("HDMI 已出画面；Ctrl+C 或 HDMI 窗口 Esc/Q 停止。", flush=True)
                    announced = True
            time.sleep(0.25)
        if hdmi.returncode:
            raise RuntimeError("HDMI 启动或运行失败，请查看 " + str(output / "hdmi-worker.log"))
        session["stopReason"] = "HDMI closed or duration complete"
        return 0
    except StopRequested:
        session["stopReason"] = "requested"
        return 0
    except Exception as error:
        session["error"] = str(error)
        raise
    finally:
        try:
            stop_owned(hdmi, output / "hdmi/stop.request")
        finally:
            # An existing encoder is never terminated by this wrapper.
            stop_owned(source, output / "evidence/stop.request")
            for log in logs:
                log.close()
            session.update(
                sourceExitCode=source.returncode if source else None,
                hdmiExitCode=hdmi.returncode if hdmi else None,
            )
            write_json(output / "session.json", session)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output", type=Path, help="new session directory; default uses a unique timestamp"
    )
    p.add_argument("--seconds", type=int, default=0, help="0 keeps running until Ctrl+C/Esc/Q")
    p.add_argument(
        "--handover",
        action="store_true",
        help="allow the existing controller to stop/restore its stream",
    )
    a = p.parse_args()
    if not 0 <= a.seconds <= 3600:
        p.error("seconds must be 0..3600")
    tag = (
        "standalone-"
        + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    output = (a.output or ROOT / "lab8k-camera" / tag).resolve()
    # Saved source commands are discovered under this established runtime tree.
    if output.parent != (ROOT / "lab8k-camera").resolve():
        p.error("--output must be a new direct child of " + str(ROOT / "lab8k-camera"))
    stopping = [False]
    signal.signal(signal.SIGINT, lambda *_: stopping.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: stopping.__setitem__(0, True))
    try:
        return run(output, a.seconds, a.handover, stopping)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
