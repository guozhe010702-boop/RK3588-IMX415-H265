"""Opt-in scheduling for the vendor AIQ RAW hand-off, independent of IRQ tuning.

Only three known, blocking RAW transport workers receive SCHED_RR/5. Algorithms,
the capture encoder, IRQs and CPU affinities retain their original policies.
Changes are journalled before application and restored using task start times,
so a recycled PID/TID or another administrator's setting is never overwritten.
"""
import copy
import json
import os
from pathlib import Path
import threading
from .support import atomic_json


WORKERS = frozenset(('xc:isp_tx_poll', 'xc:isp_rx_poll', 'xc:RawProcThrea'))
PRIORITY = 5


def high_rate(config):
    return (config.get('width', 0) >= 3840 and config.get('height', 0) >= 2160
            and config.get('fps', 0) >= 50)


class LinuxTasks:
    def __init__(self, proc='/proc'):
        self.proc = Path(proc)

    def boot_id(self):
        return (self.proc / 'sys/kernel/random/boot_id').read_text().strip()

    def supported(self):
        try:
            return b'rockchip,rk3588\0' in (self.proc / 'device-tree/compatible').read_bytes()
        except OSError:
            return False

    def identity(self, pid, tid):
        task = self.proc / str(pid) / 'task' / str(tid)
        return {'pid': pid, 'tid': tid,
                'start': (task / 'stat').read_text().rsplit(')', 1)[1].split()[19],
                'comm': (task / 'comm').read_text().strip(),
                'exe': str((self.proc / str(pid) / 'exe').resolve(strict=True))}

    def same(self, row):
        try:
            actual = self.identity(row['pid'], row['tid'])
            return all(actual[k] == row[k]
                       for k in ('pid', 'tid', 'start', 'comm', 'exe'))
        except (OSError, ValueError, IndexError):
            return False

    def discover(self):
        groups = []
        for process in self.proc.glob('[0-9]*'):
            try:
                if (process / 'comm').read_text().strip() != 'rkaiq_3A_server':
                    continue
                if (process / 'exe').resolve(strict=True) != Path('/usr/bin/rkaiq_3A_server'):
                    continue
                # Match actual RAW capture ownership, not just a process name.
                if not any(fd.resolve() == Path('/dev/video0') for fd in (process / 'fd').glob('*')):
                    continue
                rows = [self.identity(int(process.name), int(t.name))
                        for t in (process / 'task').glob('[0-9]*')
                        if (t / 'comm').read_text().strip() in WORKERS]
                if len(rows) == 3 and {r['comm'] for r in rows} == WORKERS:
                    groups.append(rows)
            except (OSError, ValueError, IndexError):
                continue
        if len(groups) > 1:
            raise RuntimeError('Multiple AIQ RAW owners; scheduling left unchanged')
        return groups[0] if groups else []

    def get(self, tid):
        return {'policy': os.sched_getscheduler(tid),
                'priority': os.sched_getparam(tid).sched_priority}

    def set(self, tid, policy, priority):
        os.sched_setscheduler(tid, policy, os.sched_param(priority))


class RawScheduler:
    def __init__(self, root, tasks=None):
        self.root = Path(root)
        self.tasks = tasks or LinuxTasks()
        self.file = self.root / 'state/raw-scheduler.json'
        self.enable_file = self.root / 'state/raw-scheduler-enabled.json'
        self.lock = threading.RLock()
        self.state = None
        self.report = {'enabled': False, 'active': False, 'workers': [], 'error': None}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.report)

    def _publish_active(self):
        workers = [dict(r, originalPolicy=r['policy'], originalPriority=r['priority'],
                        policy=2, priority=PRIORITY) for r in self.state['workers']]
        self.report.update(active=True, workers=workers, error=None)

    def _read_state(self):
        if self.state is None and self.file.exists():
            state = json.loads(self.file.read_text())
            if (state.get('version') != 1 or state.get('priority') != PRIORITY
                    or len(state.get('workers', [])) != 3
                    or {r.get('comm') for r in state['workers']} != WORKERS
                    or any(r.get('exe') != '/usr/bin/rkaiq_3A_server'
                           or r.get('policy') != 0 or r.get('priority') != 0
                           for r in state['workers'])):
                raise RuntimeError('Invalid RAW scheduling journal; inspect before changing policies')
            self.state = state

    def restore(self):
        with self.lock:
            self._read_state()
            if not self.state:
                self.report.update(active=False, workers=[])
                return
            if self.state['bootId'] == self.tasks.boot_id():
                for row in self.state['workers']:
                    if not self.tasks.same(row):
                        continue
                    actual = self.tasks.get(row['tid'])
                    if actual == {'policy': 2, 'priority': PRIORITY}:
                        self.tasks.set(row['tid'], row['policy'], row['priority'])
                    # If the journal was saved before set(), there is nothing to undo.
                    # An external policy change also takes precedence over our backup.
            self.file.unlink(missing_ok=True)
            self.state = None
            self.report.update(active=False, workers=[])

    def reconcile(self, active, config):
        """Called by the control monitor, never by the GUI/SSH request thread."""
        with self.lock:
            try:
                enabled = (self.enable_file.exists()
                           and json.loads(self.enable_file.read_text()).get('enabled') is True)
                self.report['enabled'] = enabled
                if not enabled or not active or not high_rate(config):
                    self.restore()
                    self.report['error'] = None
                    return
                if not self.tasks.supported():
                    raise RuntimeError('RAW scheduling is restricted to the validated RK3588 pipeline')
                self._read_state()
                if self.state:
                    if (self.state['bootId'] == self.tasks.boot_id()
                            and all(self.tasks.same(r) and self.tasks.get(r['tid']) ==
                                    {'policy': 2, 'priority': PRIORITY}
                                    for r in self.state['workers'])):
                        self._publish_active()
                        return
                    self.restore()
                rows = self.tasks.discover()
                if not rows:
                    self.report.update(active=False, workers=[], error='Waiting for all three AIQ RAW workers')
                    return
                for row in rows:
                    row.update(self.tasks.get(row['tid']))
                    if row['policy'] != 0 or row['priority'] != 0:
                        raise RuntimeError('AIQ worker already has a custom policy; left unchanged')
                self.state = {'version': 1, 'bootId': self.tasks.boot_id(),
                              'priority': PRIORITY, 'workers': rows}
                atomic_json(self.file, self.state)
                try:
                    for row in rows:
                        if not self.tasks.same(row):
                            raise RuntimeError('AIQ worker changed during scheduling')
                        self.tasks.set(row['tid'], 2, PRIORITY)
                        if self.tasks.get(row['tid']) != {'policy': 2, 'priority': PRIORITY}:
                            raise RuntimeError('RAW scheduling readback mismatch')
                except Exception:
                    self.restore()
                    raise
                self._publish_active()
            except Exception as error:
                self.report.update(active=False, error=str(error))
