"""Private FFmpeg VPU decode -> RGA -> raw NV12 -> system ffplay HDMI."""

import os
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from .config import URL, ControlError
from .support import mpp_device_open


class HardwareDisplay:
    def __init__(self, controller, source_url=None, timestamped=False, fullscreen=False):
        self.controller = controller
        self.source_url = source_url or URL
        self.timestamped = timestamped
        self.fullscreen = fullscreen
        self.process = self.player = None
        self.lock = threading.Lock()
        self.frame = 0
        self.last_frame = 0
        self.input_size = None
        self.display_size = None
        self.error = None
        self.decoder_name = None
        self.rate = self.progress_at = None
        self.monitor_mode = None

    def snapshot(self):
        with self.lock:
            alive = self.controller.active(self.process)
            playing = self.controller.active(self.player)
            return {'running': alive and playing, 'pid': self.process.pid if alive else None,
                    'playerPid': self.player.pid if playing else None,
                    'decoder': self.decoder_name, 'inputSize': self.input_size,
                    'displaySize': self.display_size, 'frame': self.frame,
                    'monitorMode': self.monitor_mode,
                    'vpuDeviceOpen': mpp_device_open(self.process.pid if alive else None),
                    'intervalFps': self.rate,
                    'lastFrameAgeSeconds': time.monotonic() - self.last_frame if self.last_frame else 999,
                    'error': self.error, 'sourceUrl': self.source_url,
                    'timestampedPipe': self.timestamped}

    def start(self):
        if self.snapshot()['running']:
            return
        self.stop()
        c = self.controller
        width, height = c.config['width'], c.config['height']
        decoder = 'hevc_rkmpp' if c.config['codec'] == 'h265' else 'h264_rkmpp'
        env = dict(os.environ, DISPLAY=':0')
        auth = next(iter(sorted(Path('/run/user').glob('*/gdm/Xauthority'))), None)
        if auth:
            env['XAUTHORITY'] = str(auth)
            user_runtime = auth.parents[1]
            if (user_runtime / 'bus').exists():
                env['XDG_RUNTIME_DIR'] = str(user_runtime)
                env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + str(user_runtime / 'bus')
        self.monitor_mode = None
        try:
            modes = subprocess.run(['/usr/bin/xrandr', '--current'], env=env,
                                   capture_output=True, text=True, timeout=3)
            connector = None
            for line in modes.stdout.splitlines():
                if line and not line.startswith(' '):
                    connector = line.split()[0] if ' connected' in line and 'HDMI' in line else None
                if connector:
                    found = re.search(r'^\s+(\d+)x(\d+).*?([\d.]+)\*', line)
                    if found:
                        self.monitor_mode = {'connector': connector, 'width': int(found[1]),
                                             'height': int(found[2]), 'refreshHz': float(found[3])}
                        break
        except (OSError, subprocess.TimeoutExpired):
            pass
        bound_w = min(1920, (self.monitor_mode or {}).get('width', 1920))
        bound_h = min(1080, (self.monitor_mode or {}).get('height', 1080))
        ratio = min(1, bound_w / width, bound_h / height)
        w, h = int(width * ratio) // 2 * 2, int(height * ratio) // 2 * 2
        self.frame, self.last_frame, self.error = 0, 0, None
        self.rate = self.progress_at = None
        self.input_size = None
        self.display_size, self.decoder_name = [w, h], decoder
        args = [c.ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
                '-stats_period', '1', '-progress', 'pipe:2', '-rtsp_transport', 'tcp',
                '-timeout', '5000000', '-hwaccel', 'rkmpp', '-hwaccel_output_format', 'drm_prime',
                '-c:v', decoder, '-i', self.source_url + ('&' if '?' in self.source_url else '?') + 'role=hdmi', '-map', '0:v:0', '-an',
                '-vf', 'scale_rkrga=w={}:h={}:format=nv12,hwdownload,format=nv12'.format(w, h),
                '-fps_mode', 'passthrough', '-pix_fmt', 'nv12']
        if self.timestamped:
            args += ['-c:v', 'rawvideo', '-flush_packets', '1', '-f', 'nut', 'pipe:1']
            player_input = ['-f', 'nut', '-probesize', '32768', '-analyzeduration', '0']
        else:
            args += ['-f', 'rawvideo', 'pipe:1']
            player_input = ['-f', 'rawvideo', '-pixel_format', 'nv12',
                            '-video_size', '{}x{}'.format(w, h), '-framerate', str(c.config['fps'])]
        player_args = ['/usr/bin/ffplay', '-hide_banner', '-loglevel', 'info', '-window_title',
                       'IMX415 VPU decode / HDMI', '-noinfbuf', '-framedrop']
        if self.fullscreen:
            env['SDL_VIDEO_WINDOW_POS'] = '0,0'
            env['SDL_VIDEO_FULLSCREEN_DISPLAY'] = '0'
            player_args += ['-fs', '-left', '0', '-top', '0']
        player_args += player_input + ['-i', 'pipe:0']
        (c.root / 'logs/preview-commands.json').write_text(
            json.dumps({'decoder': args, 'player': player_args}, indent=2))
        try:
            self.process = subprocess.Popen(args, env=c.environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            with open(c.root / 'logs/preview.log', 'ab', buffering=0) as log:
                self.player = subprocess.Popen(player_args,
                    env=env, stdin=self.process.stdout, stdout=subprocess.DEVNULL,
                    stderr=log, start_new_session=True)
            self.process.stdout.close()
            threading.Thread(target=self.read, args=(self.process,), daemon=True).start()
            time.sleep(0.5)
            if not self.snapshot()['running']:
                raise ControlError('Board hardware decoder or HDMI player exited; see preview log')
        except Exception as error:
            self.stop()
            self.error = str(error)
            raise

    def read(self, process):
        try:
            with open(self.controller.root / 'logs/preview-decode.log', 'a', buffering=1) as log:
                for raw in process.stderr:
                    text = raw.decode('utf-8', errors='replace').strip()
                    log.write(text + '\n')
                    with self.lock:
                        if self.process is not process:
                            continue
                        match = re.search(r'Video:.*?,.*?\b(\d{2,5})x(\d{2,5})', text)
                        if match and self.input_size is None:
                            self.input_size = [int(match[1]), int(match[2])]
                        if text.startswith('frame='):
                            frame = int(text.split('=', 1)[1])
                            now = time.monotonic()
                            if self.progress_at is not None and now > self.progress_at and frame >= self.frame:
                                self.rate = (frame - self.frame) / (now - self.progress_at)
                            self.progress_at = now
                            if frame > self.frame:
                                self.last_frame = time.monotonic()
                            self.frame = frame
                        if re.search(r'error|failed|Error|Failed', text):
                            self.error = text[-1000:]
        finally:
            process.stderr.close()

    def stop(self):
        # Closing the reader first also releases a decoder blocked writing raw frames.
        self.controller.stop_child(self.player, 3)
        self.controller.stop_child(self.process, 3)
        with self.lock:
            self.player = self.process = None
