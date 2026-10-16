"""One-second, best-effort Linux telemetry. No camera opens or control mutations."""

from pathlib import Path
import copy
import json
import os
import re
import threading
import time
import urllib.request
from .support import stamp, tail


class Rates:
    def __init__(self):
        self.previous = {}

    def delta(self, key, identity, value, now):
        old = self.previous.pop(key, None)
        if value is None:
            return None
        self.previous[key] = (identity, value, now)
        if not old or old[0] != identity or value < old[1] or now <= old[2]:
            return None
        return (value - old[1]) / (now - old[2])


def read_number(path):
    try:
        return float(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def api(path):
    try:
        with urllib.request.urlopen('http://127.0.0.1:9997/v3/' + path, timeout=0.4) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}


def proc_usage(pid):
    try:
        # comm may contain spaces and parentheses; fields after its final ')' are stable.
        fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
        return (fields[19], (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                int(fields[21]) * os.sysconf('SC_PAGE_SIZE'))
    except (OSError, ValueError, IndexError):
        return None


def session_rates(items, rates, now):
    result = []
    live = set()
    for item in items:
        if item.get('path') != 'imx415' or item.get('state') != 'read':
            continue
        from urllib.parse import parse_qs
        query = parse_qs(item.get('query', '').lstrip('?'))
        client = query.get('console', [None])[0]
        if not client or not re.fullmatch(r'[a-f0-9]{32}', client):
            continue
        ident = item.get('id')
        key = 'session:' + str(ident)
        live.add(key)
        rate = rates.delta(key, ident, item.get('outboundBytes'), now)
        result.append({'clientId': client, 'sessionId': ident,
                       'mbps': rate * 8 / 1e6 if rate is not None else None})
    for key in list(rates.previous):
        if key.startswith('session:') and key not in live:
            del rates.previous[key]
    return result


class BoardMetrics:
    def __init__(self, controller):
        self.controller = controller
        self.rates = Rates()
        self.cached = {}
        self.media = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.capture_marker = None
        self.capture_at = None
        self.capture_fps = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='board-telemetry')
        self.thread.start()

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.cached)
        age = time.monotonic() - result['monotonic'] if result.get('monotonic') is not None else None
        result.update(ageSeconds=round(age, 3) if age is not None else None, stale=age is None or age > 3)
        return result

    def run(self):
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.sample()
            except Exception as error:
                with self.lock:
                    self.cached['samplerError'] = str(error)
            self.stop_event.wait(max(0.05, 1 - (time.monotonic() - started)))

    def sample(self):
        c = self.controller
        # Never wait for a long-running lifecycle operation holding the controller lock.
        if not c.lock.acquire(blocking=False):
            return
        try:
            pid = c.capture.pid if c.active(c.capture) else None
            decoder = c.decoder.snapshot() if hasattr(c, 'decoder') else {}
            progress, log, config = dict(c.progress), c.capture_log, dict(c.config)
        finally:
            c.lock.release()
        now = time.monotonic()
        media = api('paths/get/imx415')
        sessions = api('rtspsessions/list?itemsPerPage=1000')
        frame = int(progress.get('frame', 0) or 0) if pid else None
        encoded = progress.get('intervalFps') if pid else None
        raw = None
        if pid:
            for line in tail(log, 100):
                match = re.search(r'AV_CAPTURE frames=(\d+) gaps=(\d+) width=(\d+) height=(\d+) errors=(\d+) mono_us=(\d+)', line)
                if match:
                    raw = dict(zip(('frames', 'sequenceGaps', 'width', 'height', 'errors', 'monotonicUs'), map(int, match.groups())))
        marker = (pid, raw.get('frames')) if raw else None
        if marker != self.capture_marker:
            self.capture_marker, self.capture_at = marker, now if marker else None
            self.capture_fps = self.rates.delta('capture', pid, raw['frames'] if raw else None,
                raw['monotonicUs'] / 1e6 if raw else now)
        capture_age = now - self.capture_at if self.capture_at is not None else None
        capture_fps = self.capture_fps
        if capture_age is None or capture_age > 3:
            capture_fps = None
        capture = dict(raw or {}, fps=capture_fps, ageSeconds=capture_age,
                       available=raw is not None, stale=capture_age is None or capture_age > 3)
        dec_fps = decoder.get('intervalFps')
        decoder['fps'] = dec_fps if decoder.get('lastFrameAgeSeconds', 999) < 4 else None
        inbound = self.rates.delta('path', media.get('source'), media.get('inboundBytes') if media.get('ready') else None, now)
        interfaces = []
        for folder in sorted(Path('/sys/class/net').glob('*')):
            try:
                if folder.name == 'lo' or (folder / 'operstate').read_text().strip() != 'up':
                    continue
                identity = (folder / 'ifindex').read_text().strip()
                tx = self.rates.delta('tx:' + folder.name, identity, read_number(folder / 'statistics/tx_bytes'), now)
                rx = self.rates.delta('rx:' + folder.name, identity, read_number(folder / 'statistics/rx_bytes'), now)
                speed = read_number(folder / 'speed')
                speed = speed if speed and speed > 0 else None
                interfaces.append({'name': folder.name, 'linkMbps': speed,
                    'txMbps': tx * 8 / 1e6 if tx is not None else None,
                    'rxMbps': rx * 8 / 1e6 if rx is not None else None,
                    'txUtilizationPercent': tx * 8 / 1e4 / speed if tx is not None and speed else None,
                    'rxUtilizationPercent': rx * 8 / 1e4 / speed if rx is not None and speed else None})
            except OSError:
                continue
        processes = {}
        for name, proc in [('encoder', pid), ('decoder', decoder.get('pid')), ('controller', os.getpid())]:
            usage = proc_usage(proc) if proc else None
            rate = self.rates.delta('cpu:' + name, (proc, usage[0]) if usage else None, usage[1] if usage else None, now)
            processes[name] = {'cpuPercent': rate * 100 if rate is not None else None,
                               'rssBytes': usage[2] if usage else None}
        temperatures = []
        for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
            temp = read_number(zone / 'temp')
            if temp is not None:
                temperatures.append({'name': (zone / 'type').read_text().strip(), 'celsius': temp / 1000})
        frequencies = []
        for dev in Path('/sys/class/devfreq').glob('*'):
            if any(name in dev.name for name in ('rkvenc', 'rkvdec', 'vpu')):
                frequencies.append({'name': dev.name, 'frequencyHz': read_number(dev / 'cur_freq')})
        host_cpu = None
        try:
            numbers = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:]))
            total = self.rates.delta('cpu-total', 'host', sum(numbers[:8]), now)
            idle = self.rates.delta('cpu-idle', 'host', numbers[3] + numbers[4], now)
            if total and idle is not None:
                host_cpu = 100 * (1 - idle / total)
        except (OSError, ValueError, IndexError):
            pass
        if not c.last_frame_at or now - c.last_frame_at > 4:
            encoded = None
        result = {'schemaVersion': 1, 'sampledAt': stamp(), 'monotonic': now,
                  'capture': capture, 'encoderFps': encoded, 'decoder': decoder,
                  'targetBitrate': config['bitrate'],
                  'rtspMbps': inbound * 8 / 1e6 if inbound is not None else None,
                  'clients': session_rates(sessions.get('items', []), self.rates, now),
                  'interfaces': interfaces, 'processes': processes, 'hostCpuPercent': host_cpu,
                  'temperatures': temperatures, 'vpu': frequencies}
        with self.lock:
            self.cached, self.media = result, media
