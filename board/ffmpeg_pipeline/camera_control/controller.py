"""Own capture/recording/HDMI children and their shared lifecycle state.

Methods run in the Unix-socket service, not in each SSH CLI invocation.
The operation lock serializes mutations; the state lock protects process state.
"""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from .config import ROOT, DEFAULTS, URL, MIN_FREE, ControlError, validate_config
from .support import atomic_json, camera_owners, camera_capabilities, run_id, sensor_frame_rate, stamp, tail
from .metrics import BoardMetrics
from .decoder import HardwareDisplay


class Controller:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        for folder in ("state", "logs", "recordings", "snapshots"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.ffmpeg = str(self.root / "runtime/bin/ffmpeg")
        self.ffprobe = str(self.root / "runtime/bin/ffprobe")
        self.environment = dict(
            os.environ,
            LD_LIBRARY_PATH=str(self.root / "runtime/lib") + ":" + str(self.root / "runtime/lib64"),
        )
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.capture = self.recorder = self.preview = None
        self.capture_log = self.record_log = None
        self.capture_started = self.record_started = None
        self.capture_stopped_at = 0.0
        self.record_temp = None
        self.progress = {}
        self.progress_at = None
        self.last_frame_at = 0.0
        self.last_error = None
        self.want_capture = False
        self.want_preview = False
        self.retry_at = 0.0
        self.retry_times = []
        self.last_recording = None
        previous = self.root / "state/last-recording.json"
        if previous.exists():
            try:
                self.last_recording = json.loads(previous.read_text())
            except ValueError:
                pass
        self.closed = False
        self.config = validate_config(
            json.loads((self.root / "config.json").read_text())
            if (self.root / "config.json").exists()
            else {}
        )
        self.decoder = HardwareDisplay(self)
        self.telemetry = BoardMetrics(self)
        self.actual_capture = None

    def active(self, process):
        return process is not None and process.poll() is None

    def check(self):
        encoders = []
        if Path(self.ffmpeg).is_file():
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            encoders = [
                name
                for name in ("hevc_rkmpp", "h264_rkmpp")
                if re.search(r"\b" + name + r"\b", result.stdout)
            ]
        return {
            "ffmpeg": self.ffmpeg,
            "encoders": encoders,
            "vpuDevicePresent": Path("/dev/mpp_service").exists(),
            "sensorFramesPerSecond": sensor_frame_rate(self.config["device"]),
            "cameraCapabilities": camera_capabilities(self.config["device"]),
            "decodeBackend": "rkmpp+rga+ffplay",
            "cameraPresent": Path(self.config["device"]).exists(),
            "config": self.config,
            "runtimeBuilt": Path(self.root / "runtime/build-manifest.json").exists(),
            "freeBytes": shutil.disk_usage(self.root).free,
        }

    def media_path(self):
        if self.telemetry.thread is not None:
            with self.telemetry.lock:
                return dict(self.telemetry.media)
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:9997/v3/paths/get/imx415", timeout=0.7
            ) as response:
                return json.load(response)
        except (OSError, ValueError):
            return {}

    def status(self):
        with self.lock:
            media = self.media_path()
            capture_alive = self.active(self.capture)
            recent = self.last_frame_at > time.monotonic() - 4
            device_open = False
            if capture_alive:
                for fd in Path("/proc/{}/fd".format(self.capture.pid)).glob("*"):
                    try:
                        if os.readlink(str(fd)) in (
                            "/dev/mpp_service",
                            "/dev/mpp-service",
                            "/dev/rkvenc",
                        ):
                            device_open = True
                    except OSError:
                        pass
            frame = int(self.progress.get("frame", "0") or 0)
            actual = self.actual_capture if capture_alive else None
            if capture_alive and frame:
                for line in tail(self.capture_log, 80):
                    found = re.search(
                        r"Video: rawvideo.*?\b(nv12)\b.*?(\d+)x(\d+).*?([\d.]+) fps", line
                    )
                    if found:
                        actual = {
                            "pixelFormat": found[1],
                            "width": int(found[2]),
                            "height": int(found[3]),
                            "reportedFps": float(found[4]),
                        }
                        self.actual_capture = actual
                        break
            return {
                "sampledAt": stamp(),
                "serviceRunning": True,
                "state": (
                    "running"
                    if capture_alive and recent and media.get("ready")
                    else (
                        "starting"
                        if capture_alive
                        else ("recovering" if self.want_capture else "stopped")
                    )
                ),
                "config": self.config,
                "encoder": "hevc_rkmpp" if self.config["codec"] == "h265" else "h264_rkmpp",
                "actualCapture": actual,
                "capturePid": self.capture.pid if capture_alive else None,
                "captureStartedAt": self.capture_started,
                "frame": frame,
                "fps": self.progress.get("fps"),
                "outTimeUs": self.progress.get("out_time_us"),
                "duplicateFrames": self.progress.get("dup_frames"),
                "droppedFrames": self.progress.get("drop_frames"),
                "lastFrameAgeSeconds": (
                    round(time.monotonic() - self.last_frame_at, 3) if self.last_frame_at else None
                ),
                "vpuDeviceOpen": device_open,
                "rtspReady": bool(media.get("ready")),
                "rtspPath": "/imx415",
                "rtspPort": 8554,
                "readers": len(media.get("readers", [])),
                "previewRunning": self.decoder.snapshot()["running"],
                "boardDecode": self.decoder.snapshot(),
                "metrics": self.telemetry.snapshot(),
                "recording": self.active(self.recorder),
                "recordingStartedAt": self.record_started,
                "recordingFile": str(self.record_temp) if self.record_temp else None,
                "lastRecording": self.last_recording,
                "freeBytes": shutil.disk_usage(self.root).free,
                "lastError": self.last_error,
            }

    def read_progress(self, process):
        block = {}
        try:
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if separator:
                    block[key] = value
                if key == "progress":
                    with self.lock:
                        if process is self.capture:
                            now = time.monotonic()
                            if self.progress_at is not None and now > self.progress_at:
                                increment = int(block.get('frame', 0) or 0) - int(self.progress.get('frame', 0) or 0)
                                if increment >= 0:
                                    block['intervalFps'] = increment / (now - self.progress_at)
                            self.progress_at = now
                            if int(block.get("frame", "0") or 0) > int(
                                self.progress.get("frame", "0") or 0
                            ):
                                self.last_frame_at = time.monotonic()
                            self.progress = dict(block)
                    block = {}
        finally:
            process.stdout.close()

    def spawn_logged(self, arguments, log_path, progress=False, private=True):
        with open(log_path, "ab", buffering=0) as output:
            return subprocess.Popen(
                arguments,
                env=self.environment if private else os.environ,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if progress else subprocess.DEVNULL,
                stderr=output,
                text=progress,
                bufsize=1 if progress else -1,
                start_new_session=True,
            )

    def begin_capture(self):
        # The BSP camera pipeline needs a short settle period after STREAMOFF.
        time.sleep(max(0, 0.5 - (time.monotonic() - self.capture_stopped_at)))
        device = self.config["device"]
        owners = camera_owners(device)
        if owners:
            raise ControlError("Camera busy; owner PID(s): " + " ".join(owners))
        c = self.config
        source_fps = sensor_frame_rate(device)
        if source_fps is None and c['fps'] > 30:
            raise ControlError('Cannot verify sensor frame rate; high fps request rejected')
        source_fps = source_fps or c["fps"]
        if c["fps"] > source_fps + 0.01:
            raise ControlError(
                "Requested fps exceeds actual sensor frame interval: " + str(source_fps)
            )
        timing = "setpts=N/({}*TB)".format(source_fps)
        if c["fps"] < source_fps - 0.01:
            timing += ",fps=fps={}:start_time=0".format(c["fps"])
        encoder = "hevc_rkmpp" if c["codec"] == "h265" else "h264_rkmpp"
        if encoder not in self.check()["encoders"]:
            raise ControlError("Required hardware encoder unavailable: " + encoder)
        self.capture_log = self.root / "logs" / ("capture-" + run_id() + ".log")
        args = [
            self.ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-loglevel",
            "info",
            "-stats_period",
            "1",
            "-progress",
            "pipe:1",
            "-f",
            "v4l2",
            "-capture_buffers",
            "16",
            "-thread_queue_size",
            "4",
            "-input_format",
            "nv12",
            "-video_size",
            "{}x{}".format(c["width"], c["height"]),
            "-framerate",
            str(source_fps),
            "-i",
            device,
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            encoder,
            "-rc_mode",
            "CBR",
            "-b:v",
            str(c["bitrate"]),
            "-maxrate",
            str(c["bitrate"]),
            "-minrate",
            str(c["bitrate"]),
            "-g",
            str(c["gop"]),
            "-bf",
            "0",
            "-vf",
            timing,
            "-fps_mode",
            "passthrough",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            URL,
        ]
        self.progress = {}
        self.actual_capture = None
        self.progress_at = None
        self.last_frame_at = 0.0
        self.capture = self.spawn_logged(args, self.capture_log, progress=True)
        self.capture_started = stamp()
        threading.Thread(target=self.read_progress, args=(self.capture,), daemon=True).start()

    def stop_child(self, process, timeout=15):
        if self.active(process):
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
                return False
        return True

    def start(self, config=None):
        with self.lock:
            requested = validate_config(config if config is not None else self.config)
            if self.recorder is not None:
                raise ControlError("Stop and finalize recording before changing the stream")
            if self.active(self.capture) and requested == self.config:
                return self.status()
            sensor_fps = sensor_frame_rate(requested["device"])
            if sensor_fps is None and requested['fps'] > 30:
                raise ControlError('Cannot verify sensor frame rate; high fps request rejected')
            if sensor_fps and requested["fps"] > sensor_fps + 0.01:
                raise ControlError(
                    "Requested fps exceeds actual sensor frame interval: " + str(sensor_fps)
                )
            previous = dict(self.config)
            restore = self.active(self.capture)
            preview = self.want_preview
            self.want_preview = False
            self.want_capture = False
            self.stop_child(self.capture)
            self.capture_stopped_at = time.monotonic()
            self.decoder.stop()
            self.preview = None
            self.capture = None
            self.retry_times = []
        try:
            state = self.launch_ready(requested)
            self.want_preview = preview
            self.last_error = None
            return state
        except Exception as error:
            message = str(error)
            with self.lock:
                self.want_capture = False
                self.stop_child(self.capture)
                self.capture = None
                self.config = previous
                atomic_json(self.root / "config.json", previous)
            recovery = {"attempted": restore, "restored": False}
            if restore:
                try:
                    self.launch_ready(previous)
                    self.want_preview = preview
                    recovery["restored"] = True
                except Exception as failure:
                    self.want_capture = False
                    self.stop_child(self.capture)
                    self.capture = None
                    recovery["error"] = str(failure)
            self.last_error = {"at": stamp(), "message": message, "recovery": recovery}
            raise ControlError(message, recovery)

    def launch_ready(self, config):
        for attempt in range(2):
            try:
                return self.launch_ready_attempt(config)
            except ControlError as error:
                if attempt or "Encoder did not produce a ready stream" not in str(error):
                    raise
                self.capture_stopped_at = time.monotonic()

    def launch_ready_attempt(self, config):
        with self.lock:
            self.config = dict(config)
            atomic_json(self.root / "config.json", self.config)
            self.begin_capture()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.status()
            if state["state"] == "running":
                actual = state.get("actualCapture")
                if actual and (
                    actual["width"] != config["width"] or actual["height"] != config["height"]
                ):
                    raise ControlError(
                        "Driver selected a different capture size: " + json.dumps(actual)
                    )
                self.want_capture = True
                return state
            if not self.active(self.capture):
                break
            time.sleep(0.1)
        with self.lock:
            self.want_capture = False
            self.stop_child(self.capture, 3)
            self.capture = None
            self.last_error = {
                "at": stamp(),
                "message": "Encoder did not produce a ready stream",
                "log": tail(self.capture_log, 15),
            }
        raise ControlError(json.dumps(self.last_error))

    def record_start(self):
        with self.lock:
            if self.recorder is not None:
                raise ControlError("A recording is already open")
            if self.status()["state"] != "running":
                raise ControlError("Start a ready live stream before recording")
            if shutil.disk_usage(self.root).free < MIN_FREE:
                raise ControlError("Less than 1 GiB free; recording refused")
            name = "imx415-" + run_id()
            self.record_temp = self.root / "recordings" / (name + ".partial.mp4")
            self.record_log = self.root / "logs" / (name + ".log")
            args = [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "info",
                "-rtsp_transport",
                "tcp",
                "-i",
                URL,
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                "-n",
            ]
            if self.config["codec"] == "h265":
                args += ["-tag:v", "hvc1"]
            args += [str(self.record_temp)]
            self.recorder = self.spawn_logged(args, self.record_log)
            self.record_started = stamp()
        time.sleep(0.3)
        if not self.active(self.recorder):
            self.record_stop()
            raise ControlError("Recording failed to start: " + str(tail(self.record_log, 12)))
        return self.status()

    def record_stop(self):
        with self.lock:
            if self.recorder is None:
                return {"recording": False, "lastRecording": self.last_recording}
            normal = self.stop_child(self.recorder)
            temporary = self.record_temp
            self.recorder = None
            self.record_started = None
            self.record_temp = None
            info = None
            if normal and temporary and temporary.exists():
                probe = subprocess.run(
                    [
                        self.ffprobe,
                        "-v",
                        "error",
                        "-show_entries",
                        "stream=codec_name,width,height,nb_frames:format=duration",
                        "-of",
                        "json",
                        str(temporary),
                    ],
                    env=self.environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if probe.returncode == 0:
                    info = json.loads(probe.stdout)
            if (
                not info
                or not info.get("streams")
                or float(info.get("format", {}).get("duration", "0")) <= 0
            ):
                self.last_error = {
                    "at": stamp(),
                    "message": "Recording did not finalize; partial file retained",
                    "file": str(temporary),
                    "log": tail(self.record_log, 12),
                }
                return {"recording": False, "error": self.last_error}
            final = temporary.with_name(temporary.name.replace(".partial.mp4", ".mp4"))
            temporary.rename(final)
            self.last_recording = {
                "file": str(final),
                "bytes": final.stat().st_size,
                "finishedAt": stamp(),
                "probe": info,
            }
            atomic_json(self.root / "state/last-recording.json", self.last_recording)
            return {"recording": False, "lastRecording": self.last_recording}

    def preview_start(self):
        with self.lock:
            if self.decoder.snapshot()['running']:
                return self.status()
            if self.status()["state"] != "running":
                raise ControlError("Stream is not ready")
            self.decoder.start()
            self.preview = self.decoder.player
        self.want_preview = True
        return self.status()

    def preview_stop(self):
        with self.lock:
            self.want_preview = False
            self.decoder.stop()
            self.preview = None
            return {"previewRunning": False}

    def snapshot(self):
        if self.status()["state"] != "running":
            raise ControlError("Stream is not ready")
        output = self.root / "snapshots" / ("imx415-" + run_id() + ".jpg")
        result = subprocess.run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-rtsp_transport",
                "tcp",
                "-i",
                URL,
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-update",
                "1",
                "-n",
                str(output),
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode or not output.exists():
            raise ControlError("Snapshot failed: " + result.stderr[-2000:])
        return {"file": str(output), "bytes": output.stat().st_size, "createdAt": stamp()}

    def stop(self):
        with self.lock:
            self.want_capture = False
            record_result = self.record_stop()
            self.preview_stop()
            self.stop_child(self.capture)
            self.capture = None
            self.capture_stopped_at = time.monotonic()
            self.progress = {}
            self.last_frame_at = 0.0
            return {"state": "stopped", "recordingResult": record_result}

    def monitor(self):
        while not self.closed:
            time.sleep(1)
            with self.lock:
                try:
                    if self.recorder is not None and (
                        not self.active(self.recorder)
                        or shutil.disk_usage(self.root).free < MIN_FREE
                    ):
                        reason = "Recorder exited or disk free space reached 1 GiB limit"
                        self.record_stop()
                        self.last_error = {"at": stamp(), "message": reason}
                    if self.want_capture and not self.active(self.capture):
                        if self.recorder is not None:
                            self.record_stop()
                        if self.capture is not None:
                            self.last_error = {
                                "at": stamp(),
                                "message": "Encoder exited; retrying",
                                "log": tail(self.capture_log, 10),
                            }
                            self.capture = None
                            self.retry_at = time.monotonic() + 1
                            self.decoder.stop()
                            self.preview = None
                        now = time.monotonic()
                        if now >= self.retry_at:
                            self.retry_times = [t for t in self.retry_times if t > now - 60]
                            if len(self.retry_times) >= 5:
                                self.want_capture = False
                                self.last_error = {
                                    "at": stamp(),
                                    "message": "Five restart failures within 60 seconds; stopped",
                                }
                            else:
                                self.retry_times.append(now)
                                self.begin_capture()
                                self.retry_at = now + 2
                    if (
                        self.want_preview
                        and not self.decoder.snapshot()['running']
                        and self.status()["state"] == "running"
                    ):
                        try:
                            self.preview_start()
                        except Exception as error:
                            # HDMI failure must never restart or disable the encoder.
                            self.want_preview = False
                            self.decoder.error = str(error)
                    atomic_json(self.root / "state/status.json", self.status())
                except Exception as error:
                    self.last_error = {"at": stamp(), "message": str(error)}

    def execute(self, action, payload):
        if action == "start":
            return self.start(payload.get("config"))
        methods = {
            "check": self.check,
            "status": self.status,
            "stop": self.stop,
            "record-start": self.record_start,
            "record-stop": self.record_stop,
            "preview-start": self.preview_start,
            "preview-stop": self.preview_stop,
            "decode-start": self.preview_start,
            "decode-stop": self.preview_stop,
            "snapshot": self.snapshot,
        }
        if action == "logs":
            lines = payload.get("lines", 40)
            if type(lines) is not int or not 1 <= lines <= 500:
                raise ControlError("lines must be 1..500")
            return {
                "capture": tail(self.capture_log, lines),
                "recording": tail(self.record_log, lines),
                "preview": tail(self.root / "logs/preview.log", lines),
            }
        if action not in methods:
            raise ControlError("Unknown action")
        return methods[action]()
