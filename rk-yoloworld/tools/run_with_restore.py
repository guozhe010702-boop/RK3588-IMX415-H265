#!/usr/bin/env python3
"""Board-only test wrapper. Probe first, temporarily hand over camera, restore in finally.

This wrapper targets this project's existing avctl controller. Plain startup is
independent and never kills a camera owner. No firmware or service enable changes.
"""
import argparse, fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = Path("/userdata/av_dev/ffmpeg_pipeline")
child = None


def stop_signal(signum, frame):
    if child and child.poll() is None:
        child.send_signal(signal.SIGINT)
    else:
        raise KeyboardInterrupt


def main():
    global child
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument(
        "--hdmi", action="store_true", help="show the same detection stream on board HDMI"
    )
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error("--seconds must be nonnegative; 0 runs until Ctrl+C")
    os.chdir(ROOT)
    sys.path.insert(0, str(CONTROL))
    from camera_control.transport import request

    state = ROOT / "state"
    state.mkdir(exist_ok=True)
    lock = open(state / "test.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(action, payload=None):
        response = request(action, payload or {})
        if not response.get("ok"):
            raise RuntimeError(str(response))
        return response["result"]

    def restore(saved):
        if saved.get("capturePid") or saved.get("state") in ("running", "starting", "recovering"):
            call("start", {"config": saved["config"]})
            if saved.get("previewRunning"):
                call("decode-start")
        actual = call("status")
        (state / "restored.json").write_text(json.dumps(actual, indent=2))
        if saved.get("capturePid"):
            if actual.get("state") != "running" or actual.get("config") != saved["config"]:
                raise RuntimeError("Original stream did not restore")
            if saved.get("previewRunning") and not actual.get("previewRunning"):
                raise RuntimeError("Original HDMI did not restore")
        print("Original video state restored.", flush=True)

    snapshot = state / "before-test.json"
    if args.restore_only:
        # Recover our own scheduling journal too, including after SIGKILL/power loss.
        from camera_control.raw_scheduler import RawScheduler

        RawScheduler(ROOT).restore()
        restore(json.loads(snapshot.read_text()))
        return
    # Runs all models + RGA without camera; runtime incompatibility never interrupts live video.
    subprocess.run(["bash", "./run_realtime_yolo_world.sh", "--probe"], check=True, timeout=600)
    saved = call("status")
    if saved.get("recording"):
        raise RuntimeError("Recording active: stop it explicitly before a detection test")
    snapshot.write_text(json.dumps(saved, indent=2))
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    tag = time.strftime("%Y%m%d-%H%M%S")
    signal.signal(signal.SIGINT, stop_signal)
    signal.signal(signal.SIGTERM, stop_signal)
    raw_policy = None
    preview = None
    try:
        call("stop")
        time.sleep(1)
        # Preserve the already-enabled policy of the saved 4K60 sensor pipeline.
        # IMX415 still reads its full 4K60 sensor mode when ISP scales to 1440p.
        # Use a separate journal; never change the original controller's setting.
        if saved.get("captureScheduling", {}).get("active"):
            from camera_control.raw_scheduler import RawScheduler

            (state / "raw-scheduler-enabled.json").write_text(json.dumps({"enabled": True}))
            raw_policy = RawScheduler(ROOT)
            raw_policy.reconcile(True, saved["config"])
            report = raw_policy.snapshot()
            print("Inherited sensor RAW scheduling: " + json.dumps(report), flush=True)
            if not report.get("active"):
                raise RuntimeError("Cannot preserve existing RAW scheduling policy")
        extra = []
        if args.hdmi:
            from hdmi_preview import Preview

            preview = Preview()
            preview.start()
            extra = ["--local-preview"]
        with (logs / (tag + ".jsonl")).open("w") as output, (logs / (tag + ".log")).open(
            "w"
        ) as errors:
            child = subprocess.Popen(
                ["bash", "./run_realtime_yolo_world.sh", "--seconds", str(args.seconds)] + extra,
                stdout=output,
                stderr=errors,
            )
            child.wait(timeout=args.seconds + 600 if args.seconds else None)
            if child.returncode:
                raise RuntimeError("Detection failed: see " + str(logs / (tag + ".log")))
    finally:
        # A second Ctrl+C must not interrupt camera release / original-stream restore.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if child and child.poll() is None:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                # Application owns its encoder. Do not kill arbitrary ffmpeg processes.
                child.terminate()
                child.wait(timeout=15)
        try:
            try:
                if preview:
                    preview.stop()
            finally:
                if raw_policy:
                    raw_policy.restore()
        finally:
            restore(saved)


if __name__ == "__main__":
    main()
