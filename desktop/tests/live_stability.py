"""Actual console SSH/RTSP long test; visible paints and startup gaps stay distinct.

ADB provisions one uniquely tagged, temporary SSH key and verifies the host key.
Control and telemetry then use the production SSH worker; video travels over LAN.
No stream reconfiguration or board stop is performed by this test.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid

import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop"))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow
from evm_console.ssh import trust_host


def summarize(rows, boards, duration, requested, completed):
    # Exclude only initial decoder/keyframe startup; preserve errors and gaps
    # before that boundary separately in raw logs and initialGapCount.
    warm = [r for r in rows if r["elapsedSeconds"] >= 10]
    b = [r for r in boards if r["elapsedSeconds"] >= 10]
    result = {"scope": "REAL_CAMERA_4K60_LAN_30MIN", "completed": completed,
        "durationSeconds": duration, "requestedSeconds": requested,
        "samples": len(rows), "boardSamples": len(boards), "warmupSeconds": 10}
    keys = ["capture_fps", "encode_fps", "board_decode_fps", "pc_decode_fps", "qt_paint_fps",
            "rtsp_mbps", "pc_session_mbps", "nic_tx_mbps", "pc_cpu_percent", "gui_cpu_percent",
            "gui_rss_mib", "pc_decoder_rss_mib", "capture_hold_max_ms", "capture_age_max_ms",
            "board_memory_percent", "pc_memory_percent", "board_cpu_percent", "pc_session_link_percent",
            "nic_tx_percent"]
    result["averages"] = {k: statistics.mean([r[k] for r in warm if r.get(k) is not None])
        if any(r.get(k) is not None for r in warm) else None for k in keys}
    if warm:
        result["validResourceSamples"] = sum(all(r.get(k) is not None for k in [
            "board_memory_percent","pc_memory_percent","board_cpu_percent","pc_cpu_percent",
            "pc_session_mbps","pc_session_link_percent","nic_tx_percent"]) for r in warm)
        result.update(minimizedSamples=sum(r["windowMinimized"] for r in warm),
            staleSamples=sum(bool(r.get("board_stale")) for r in warm),
            hiddenSamples=sum(not r["windowVisible"] for r in warm),
            below55PaintSamples=sum(r.get("qt_paint_fps") is not None and r["qt_paint_fps"] < 55 for r in warm),
            pcDecodeErrorsAfterWarmup=warm[-1]["pc_decode_errors"]-warm[0]["pc_decode_errors"],
            reconnects=warm[-1]["reconnects"]-warm[0]["reconnects"],
            firstFrameSeconds=warm[-1].get("first_frame_s"),
            guiMemoryGrowthMiB=warm[-1]["gui_rss_mib"]-warm[0]["gui_rss_mib"],
            decoderMemoryGrowthMiB=warm[-1]["pc_decoder_rss_mib"]-warm[0]["pc_decoder_rss_mib"])
        dt = warm[-1]["elapsedSeconds"] - warm[0]["elapsedSeconds"]
        if dt > 0:
            result["pcDecodeFps"] = (warm[-1]["decodedCount"]-warm[0]["decodedCount"])/dt
            result["qtPaintFps"] = (warm[-1]["paintedCount"]-warm[0]["paintedCount"])/dt
        result["pcCounterWindowSeconds"] = dt
    if len(b) > 1:
        first, last = b[0], b[-1]
        dt = last["monotonic"]-first["monotonic"]
        c0, c1 = first["capture"], last["capture"]
        result.update(counterWindowSeconds=dt,
            captureFps=(c1["frames"]-c0["frames"])/((c1["monotonicUs"]-c0["monotonicUs"])/1e6),
            encoderFps=(last["encoded"]-first["encoded"])/dt,
            boardDecodeFps=(last["decoded"]-first["decoded"])/dt,
            additionalSequenceGaps=c1["sequenceGaps"]-c0["sequenceGaps"],
            initialGapCount=boards[0]["capture"]["sequenceGaps"],
            captureErrors=c1["errors"]-c0["errors"],
            duplicateFrames=last["duplicates"]-first["duplicates"],
            droppedFrames=last["drops"]-first["drops"],
            captureProcessChanged=len({r["pid"] for r in boards}) != 1)
        result["hardwareAndModeValid"] = all(r["hardwareAndModeValid"] for r in boards)
    long_enough = (duration >= 1800 and result.get("counterWindowSeconds", 0) >= 1790
                   and result.get("pcCounterWindowSeconds", 0) >= 1790)
    result["passed"] = bool(completed and long_enough
        and all(59 <= result.get(k, 0) <= 62 for k in ["captureFps", "encoderFps", "boardDecodeFps", "pcDecodeFps"])
        and 55 <= result.get("qtPaintFps", 0) <= 62
        and all(result.get(k) == 0 for k in ["additionalSequenceGaps", "captureErrors", "duplicateFrames",
            "droppedFrames", "pcDecodeErrorsAfterWarmup", "reconnects", "minimizedSamples", "hiddenSamples", "staleSamples"])
        and not result.get("captureProcessChanged", True))
    result["passed"] = result["passed"] and result.get("hardwareAndModeValid", False) and bool(warm) and all(
        r.get("pc_decode_size") == "3840x2160" and r.get("preview_size") == "1280x720" for r in warm)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=1815)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="192.168.2.221")
    parser.add_argument("--adb", type=Path, default=ROOT.parent / "Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe")
    parser.add_argument("--provision-temporary-key", action="store_true", required=True)
    parser.add_argument("--keep-visible", action="store_true")
    parser.add_argument("--wait-visible", action="store_true",
        help="Begin the duration after 15 seconds visibly decoding; report earlier waiting separately")
    parser.add_argument("--monitor-window", action="store_true",
        help="Test-only floating tool window, no taskbar/minimize button; real paints are still measured")
    parser.add_argument("--capture-trends", action="store_true", help="Save overview and expanded trend screenshots")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["EVM_CONSOLE_DATA"] = str((args.output / "user-data").resolve())
    def adb(*a):
        return subprocess.check_output([str(args.adb), *a], timeout=20, text=True)
    tag = "av-dev-acceptance-" + uuid.uuid4().hex
    private, public = args.output / "temporary-key", args.output / "temporary-key.pub"
    remote_public, remote_helper = "/tmp/" + tag + ".pub", "/tmp/" + tag + ".py"
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(private))
    public.write_text(key.get_name()+" "+key.get_base64()+" "+tag+"\n")
    rows, boards, completed = [], [], False
    window = None
    began = time.monotonic()
    sample_file = board_file = None
    measurement_started = None
    visible_since = None
    waiting_seconds = 0
    ended_at = None
    try:
        adb("push", str(public), remote_public)
        adb("push", str(ROOT / "tools/tests/temporary_ssh_key.py"), remote_helper)
        assert json.loads(adb("shell", "python3 "+remote_helper+" add "+remote_public))["added"]
        host_key = adb("shell", "cat /etc/ssh/ssh_host_ed25519_key.pub").split()
        trust_host({"host": args.host, "type": host_key[0], "key": host_key[1]})
        app = QApplication([])
        window = MainWindow()
        window.setWindowTitle("真实 4K60 · SSH / RTSP 长测 · 请保持窗口可见")
        if args.keep_visible:
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if args.monitor_window:
            window.setWindowFlag(Qt.WindowType.Tool, True)
            window.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
            window.resize(1100, 780)
        window.host.setText(args.host)
        window.auth.setCurrentIndex(1)
        window.key_file.setText(str(private.resolve()))
        window.preview_quality.setCurrentText("性能 60 fps")
        window.show()
        if args.keep_visible:
            QTimer.singleShot(200, window.showNormal)
        window.select_page(4)
        sample_file = (args.output / "qt-samples.jsonl").open("w", encoding="utf-8")
        board_file = (args.output / "board-samples.jsonl").open("w", encoding="utf-8")
        began = time.monotonic()

        def sample(row):
            r = dict(row, elapsedSeconds=time.monotonic()-(measurement_started or began),
                wallElapsedSeconds=time.monotonic()-began,
                measuring=not args.wait_visible or measurement_started is not None,
                windowMinimized=window.isMinimized(), windowVisible=window.isVisible(),
                decodedCount=window.video.decoded_frames, paintedCount=window.canvas.painted_frames)
            if not args.wait_visible or measurement_started is not None:
                rows.append(r)
            sample_file.write(json.dumps(r)+"\n")
            sample_file.flush()
            if r["measuring"] and len(rows) % 60 == 0:
                print(json.dumps({k:r.get(k) for k in ["elapsedSeconds","capture_gaps","pc_decode_fps","qt_paint_fps","windowMinimized"]}), flush=True)
            if len(rows) == 20:
                window.grab().save(str(args.output / "console.png"))
                window.side_panel.grab().save(str(args.output / "performance-overview.png"))
                if args.capture_trends:
                    window.trend_toggle.setChecked(True)
                    def capture_trends():
                        scroll = window.pages.currentWidget()
                        scroll.ensureWidgetVisible(window.fps_trend)
                        def save():
                            window.side_panel.grab().save(str(args.output / "performance-trends.png"))
                            scroll.verticalScrollBar().setValue(0)
                            window.trend_toggle.setChecked(False)
                        QTimer.singleShot(150, save)
                    QTimer.singleShot(150, capture_trends)

        def board(state):
            board_file.write(json.dumps(state)+"\n")
            board_file.flush()
            m = state.get("metrics", {})
            capture = m.get("capture", {})
            if capture.get("frames") is None:
                return
            entry = {"elapsedSeconds":time.monotonic()-(measurement_started or began), "capture":capture,
                "monotonic":m["monotonic"], "pid":state.get("capturePid"),
                "encoded":state.get("frame",0), "decoded":state.get("boardDecode",{}).get("frame",0),
                "hardwareAndModeValid": state.get("state") == "running" and state.get("encoder") == "hevc_rkmpp"
                    and state.get("vpuDeviceOpen") is True
                    and all(state.get("config",{}).get(k) == v for k,v in {"width":3840,"height":2160,"fps":60}.items())
                    and (state.get("actualCapture") or {}).get("reportedFps",0) >= 59
                    and state.get("boardDecode",{}).get("vpuDeviceOpen") is True
                    and state.get("boardDecode",{}).get("inputSize") == [3840,2160],
                "duplicates":int(state.get("duplicateFrames") or 0), "drops":int(state.get("droppedFrames") or 0)}
            if not args.wait_visible or measurement_started is not None:
                boards.append(entry)

        window.performance.sample.connect(sample)
        window.ssh.status.connect(board)
        window.connect_board()
        timer = QTimer()
        timer.setInterval(200)
        def finish():
            nonlocal completed, measurement_started, visible_since, waiting_seconds, ended_at
            now = time.monotonic()
            if args.wait_visible and measurement_started is None:
                ready = (window.isVisible() and not window.isMinimized() and window.ssh_connected
                         and window.video.last_frame and now-window.video.last_frame < 3)
                visible_since = (visible_since or now) if ready else None
                if visible_since and now-visible_since >= 15:
                    measurement_started = now
                    waiting_seconds = now-began
                    print(json.dumps({"measurementStarted":True,"waitingSeconds":waiting_seconds}), flush=True)
                # Do not turn an indefinitely hidden window into a passed test.
                if now-began > 3600:
                    timer.stop()
                    window.close()
                return
            if now-(measurement_started or began) >= args.seconds:
                completed = True
                ended_at = now
                timer.stop()
                window.grab().save(str(args.output / "console-final.png"))
                window.close()
        timer.timeout.connect(finish)
        timer.start()
        # Qt Tool windows do not trigger quitOnLastWindowClosed. Finish after
        # the production close handler has asynchronously stopped all workers.
        exit_timer = QTimer()
        exit_timer.setInterval(100)
        def exit_when_closed():
            if window.closing and not window.isVisible() and not any(
                worker.isRunning() for worker in (window.ssh, window.video, window.files, window.performance)):
                app.quit()
        exit_timer.timeout.connect(exit_when_closed)
        exit_timer.start()
        app.exec()
    finally:
        if sample_file:
            sample_file.close()
        if board_file:
            board_file.close()
        result = summarize(rows, boards, (ended_at or time.monotonic())-(measurement_started or began), args.seconds, completed)
        result["waitingBeforeMeasurementSeconds"] = waiting_seconds
        try:
            result["temporaryKeyRemoved"] = json.loads(adb("shell", "python3 "+remote_helper+" remove "+remote_public))["removed"]
            adb("shell", "rm -f "+remote_helper+" "+remote_public)
        finally:
            private.unlink(missing_ok=True)
        (args.output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
