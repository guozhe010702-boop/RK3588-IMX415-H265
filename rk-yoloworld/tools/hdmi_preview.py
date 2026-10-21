"""Board-only H.264 VPU decode -> RGA 1080p -> timestamped NUT -> HDMI.

Reads UDP loopback only, never opens the camera. Owned processes are stopped
before the original H.265 HDMI is restored. No software decoding fallback.
"""

import json
import os
from pathlib import Path
import signal
import subprocess

ROOT = Path(__file__).resolve().parents[1]


class Preview:
    def __init__(self):
        self.decoder = self.player = self.log = None
        self.state = ROOT / "state/detection-hdmi.json"

    def start(self):
        # These are the same private video libraries as the existing av_dev pipeline.
        ffmpeg = "/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg"
        env = dict(os.environ)
        env.pop("LD_PRELOAD", None)
        env["LD_LIBRARY_PATH"] = (
            "/userdata/av_dev/ffmpeg_pipeline/runtime/lib:"
            "/userdata/av_dev/ffmpeg_pipeline/runtime/lib64"
        )
        display_env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
        display_env.pop("LD_LIBRARY_PATH", None)
        display_env.pop("LD_PRELOAD", None)
        display_env["SDL_AUDIODRIVER"] = "dummy"
        auth = next(iter(sorted(Path("/run/user").glob("*/gdm/Xauthority"))), None)
        if auth:
            display_env["XAUTHORITY"] = str(auth)
            user_runtime = auth.parents[1]
            display_env["XDG_RUNTIME_DIR"] = str(user_runtime)
            display_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(user_runtime / "bus")
        (ROOT / "logs").mkdir(exist_ok=True)
        (ROOT / "state").mkdir(exist_ok=True)
        self.log = open(ROOT / "logs/detection-hdmi.log", "wb", buffering=0)
        try:
            self.decoder = subprocess.Popen(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "info",
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                    "-probesize",
                    "32768",
                    "-analyzeduration",
                    "0",
                    "-hwaccel",
                    "rkmpp",
                    "-hwaccel_output_format",
                    "drm_prime",
                    "-c:v",
                    "h264_rkmpp",
                    "-i",
                    "udp://127.0.0.1:1236?fifo_size=32768&buffer_size=4194304&overrun_nonfatal=1",
                    "-map",
                    "0:v:0",
                    "-an",
                    "-vf",
                    "scale_rkrga=w=1920:h=1080:format=nv12,hwdownload,format=nv12",
                    "-c:v",
                    "rawvideo",
                    "-enc_time_base:v",
                    "1:1000000",
                    "-fps_mode",
                    "passthrough",
                    "-f",
                    "nut",
                    "pipe:1",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=self.log,
                env=env,
                start_new_session=True,
            )
            self.player = subprocess.Popen(
                [
                    "/usr/bin/ffplay",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-an",
                    "-fflags",
                    "nobuffer",
                    "-flags",
                    "low_delay",
                    "-framedrop",
                    "-sync",
                    "ext",
                    "-window_title",
                    "YOLO-World detection HDMI",
                    "-f",
                    "nut",
                    "-i",
                    "pipe:0",
                ],
                stdin=self.decoder.stdout,
                stdout=subprocess.DEVNULL,
                stderr=self.log,
                env=display_env,
                start_new_session=True,
            )
            self.decoder.stdout.close()
            self.state.write_text(
                json.dumps(
                    {
                        "decoderPid": self.decoder.pid,
                        "playerPid": self.player.pid,
                        "decoder": "h264_rkmpp",
                        "displaySize": [1920, 1080],
                    }
                )
            )
        except BaseException:
            self.stop()
            raise

    def stop(self):
        # Popen objects identify owned processes; never kill a PID from an old JSON file.
        for process in (self.player, self.decoder):
            if process and process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process in (self.player, self.decoder):
            if process:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.state.unlink(missing_ok=True)
        if self.log:
            self.log.close()
        self.decoder = self.player = self.log = None
