import os
import subprocess
import threading
import time
import re
import uuid
from PySide6.QtCore import QThread, Signal
from .core import FrameAssembler, executable


def preview_size(width, height, maximum):
    if width <= 0 or height <= 0:
        raise ValueError("Invalid video dimensions")
    output_width = max(2, min(maximum, width) // 2 * 2)
    return output_width, max(2, int(height * output_width / width) // 2 * 2)


def terminate(process):
    if process is not None:
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass


class VideoWorker(QThread):
    state = Signal(str)
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.desired = self.process = self.latest = None
        self.generation = 0
        self.maximum_width, self.maximum_fps = 1280, 30
        self.stop_event = threading.Event()
        self.sequence = self.frames = self.reconnects = 0
        self.last_frame = 0
        self.pid = None
        self.width = self.height = 0
        self.first_frame_seconds = None
        self.client_id = uuid.uuid4().hex
        self.decoded_frames = self.discarded = 0
        self.decode_errors = 0
        self.input_size = None
        self.source_fps = None

    def metrics_snapshot(self):
        with self.lock:
            return {'clientId': self.client_id, 'generation': (self.generation, self.pid),
                    'pid': self.pid, 'decodedFrames': self.decoded_frames,
                    'discarded': self.discarded, 'lastFrame': self.last_frame,
                    'inputSize': self.input_size, 'previewSize': [self.width, self.height],
                    'reconnects': self.reconnects, 'maximumFps': self.maximum_fps,
                    'decodeErrors': self.decode_errors,
                    'sourceFps': self.source_fps,
                    'firstFrameSeconds': self.first_frame_seconds}

    def set_quality(self, width, fps):
        with self.lock:
            self.maximum_width, self.maximum_fps = width, fps

    def configure(self, url, width, height, token):
        with self.lock:
            width, height = preview_size(width, height, self.maximum_width)
            value = (url, width, height, token, self.maximum_fps)
            changed = self.desired != value
            if changed:
                self.generation += 1
                self.latest = None
            self.desired = value
            process = self.process
        if changed:
            terminate(process)

    def pause(self):
        with self.lock:
            self.generation += 1
            self.desired = self.latest = None
            self.first_frame_seconds = None
            process = self.process
        terminate(process)
        self.state.emit("未播放")

    def shutdown(self):
        self.stop_event.set()
        self.pause()

    def take_frame(self):
        with self.lock:
            value = self.latest
            self.latest = None
            return value

    def run(self):
        while not self.stop_event.is_set():
            with self.lock:
                desired, generation = self.desired, self.generation
            if not desired:
                self.stop_event.wait(0.1)
                continue
            url, width, height, token, fps = desired
            process = stderr = watchdog = None
            activity = [time.monotonic()]
            try:
                self.state.emit("连接视频流…")
                args = [executable("ffmpeg"), "-hide_banner", "-loglevel", "info", "-nostats", "-nostdin"]
                if url.startswith("rtsp://"):
                    args += [
                        "-timeout",
                        "5000000",
                        "-rtsp_transport",
                        "tcp",
                        "-fflags",
                        "nobuffer",
                        "-flags",
                        "low_delay",
                        "-threads",
                        "0" if fps >= 60 else "2",
                    ]
                else:
                    args += ["-stream_loop", "-1", "-re", "-threads", "2"]
                filters = (
                    f"showinfo@decoded=checksum=0,fps=fps='if(gt(source_fps,0),min(source_fps,{fps}),{fps})',scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
                )
                args += [
                    "-i",
                    url + ('&' if '?' in url else '?') + 'console=' + self.client_id if url.startswith('rtsp://') else url,
                    "-map",
                    "0:v:0",
                    "-an",
                    "-filter_threads",
                    "1",
                    "-vf",
                    filters,
                    "-pix_fmt",
                    "bgr24",
                    "-threads",
                    "1",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ]
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                began = time.monotonic()
                with self.lock:
                    # pause/configure can run while Popen creates the process.
                    if generation != self.generation or self.stop_event.is_set():
                        continue
                    self.process, self.pid = process, process.pid
                    self.width, self.height = width, height
                    self.first_frame_seconds = None
                    self.input_size = None
                    self.source_fps = None
                stderr = threading.Thread(
                    target=self.drain_log, args=(process, generation), daemon=True
                )
                stderr.start()
                watchdog = threading.Thread(
                    target=self.watchdog, args=(process, generation, activity), daemon=True
                )
                watchdog.start()
                assembler = FrameAssembler(width * height * 3)
                first = True
                while not self.stop_event.is_set():
                    with self.lock:
                        if generation != self.generation:
                            break
                    chunk = process.stdout.read1(65536)
                    if not chunk:
                        break
                    frame = assembler.feed(chunk)
                    if frame:
                        now = time.monotonic()
                        activity[0] = now
                        with self.lock:
                            if generation != self.generation:
                                break
                            self.last_frame = now
                            self.frames += 1
                            self.discarded += int(self.latest is not None) + assembler.discarded_frames
                            assembler.discarded_frames = 0
                            self.sequence += 1
                            self.latest = (frame, width, height, self.sequence)
                            if first:
                                self.first_frame_seconds = now - began
                                self.state.emit("实时画面")
                                first = False
                with self.lock:
                    if generation == self.generation and not self.stop_event.is_set():
                        self.reconnects += 1
                        self.state.emit("视频中断，正在重连…")
            except Exception as error:
                with self.lock:
                    if generation == self.generation and not self.stop_event.is_set():
                        self.log.emit(str(error))
                        self.state.emit("视频连接失败，正在重试…")
            finally:
                terminate(process)
                if process:
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    if stderr:
                        stderr.join(timeout=1)
                    if watchdog:
                        watchdog.join(timeout=1)
                    for pipe in (process.stdout, process.stderr):
                        if pipe:
                            pipe.close()
                with self.lock:
                    if self.process is process:
                        self.process = self.pid = None
            self.stop_event.wait(0.5)

    def watchdog(self, process, generation, activity):
        while process.poll() is None and not self.stop_event.wait(0.25):
            with self.lock:
                stale = generation != self.generation
            if stale or time.monotonic() - activity[0] > 4:
                terminate(process)
                return

    def drain_log(self, process, generation):
        previous_n = -1
        try:
            for line in process.stderr:
                text = line.decode("utf-8", errors="replace").strip()
                with self.lock:
                    if generation != self.generation or self.stop_event.is_set():
                        return
                    found = re.search(r'showinfo@decoded.*?\bn:\s*(\d+).*?\bs:(\d+)x(\d+)', text)
                    nominal = re.search(r'showinfo@decoded.*?config in.*?frame_rate:\s*(\d+)/(\d+)', text)
                    if nominal and int(nominal[2]):
                        self.source_fps = int(nominal[1]) / int(nominal[2])
                    if found:
                        n = int(found[1])
                        self.decoded_frames += max(0, n - previous_n)
                        previous_n = n
                        self.input_size = [int(found[2]), int(found[3])]
                    elif text and 'showinfo@decoded' not in text and re.search(r'error|failed|invalid|Error|Failed|Invalid', text):
                        self.decode_errors += 1
                        self.log.emit(text[:1000])
        except (ValueError, OSError):
            pass
