"""RAW hand-off scheduling: ownership, rollback and stream lifecycle protection."""
from pathlib import Path
import copy
import json
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.raw_scheduler import RawScheduler, high_rate, WORKERS


class Tasks:
    def __init__(self):
        self.rows = [dict(pid=900, tid=10+i, start='100', comm=name,
                          exe='/usr/bin/rkaiq_3A_server')
                     for i, name in enumerate(sorted(WORKERS))]
        self.policies = {r['tid']: {'policy': 0, 'priority': 0} for r in self.rows}
        self.calls = []
        self.fail = None
        self.boot = 'first'
        self.support = True

    def boot_id(self): return self.boot
    def supported(self): return self.support
    def discover(self): return copy.deepcopy(self.rows)
    def same(self, row): return any(all(r[k] == row[k] for k in r) for r in self.rows)
    def get(self, tid): return self.policies[tid].copy()

    def set(self, tid, policy, priority):
        if tid == self.fail and policy == 2:
            raise PermissionError('scheduling denied')
        self.calls.append((tid, policy, priority))
        self.policies[tid] = {'policy': policy, 'priority': priority}


CONFIG = {'width': 3840, 'height': 2160, 'fps': 60}


@pytest.fixture
def setup(tmp_path):
    (tmp_path/'state').mkdir()
    tasks = Tasks()
    scheduler = RawScheduler(tmp_path, tasks)
    scheduler.enable_file.write_text('{"enabled":true}')
    return scheduler, tasks


def test_only_opted_in_active_high_rate_stream_changes_policy(setup):
    s, t = setup
    s.enable_file.unlink()
    s.reconcile(True, CONFIG)
    assert not t.calls
    s.enable_file.write_text('{"enabled":true}')
    s.reconcile(False, CONFIG)
    s.reconcile(True, dict(CONFIG, fps=30))
    s.reconcile(True, dict(CONFIG, width=1920, height=1080))
    assert not t.calls
    s.reconcile(True, CONFIG)
    assert s.snapshot()['active']
    assert all(r['policy'] == 2 and r['priority'] == 5 and r['originalPolicy'] == 0
               for r in s.snapshot()['workers'])
    assert t.calls == [(10, 2, 5), (11, 2, 5), (12, 2, 5)]
    s.reconcile(True, CONFIG)
    assert len(t.calls) == 3
    assert not high_rate({'width': 3840, 'height': 2160, 'fps': 30})


def test_stop_restores_exact_prior_policies(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    s.reconcile(False, CONFIG)
    assert all(p == {'policy': 0, 'priority': 0} for p in t.policies.values())
    assert not s.file.exists()
    assert not s.snapshot()['active']


def test_partial_failure_rolls_back_without_disabling_capture(setup):
    s,t = setup
    t.fail = 11
    s.reconcile(True, CONFIG)
    assert not s.snapshot()['active']
    assert 'denied' in s.snapshot()['error']
    assert all(p['policy'] == 0 for p in t.policies.values())
    assert not s.file.exists()


def test_pid_reuse_never_changes_unrelated_task(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    t.rows[0]['start'] = '200'
    t.policies[10] = {'policy': 0, 'priority': 0}
    t.calls.clear()
    s.restore()
    assert not any(tid == 10 for tid,_,_ in t.calls)


def test_external_policy_takes_precedence_on_restore(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    t.policies[10] = {'policy': 1, 'priority': 20}
    s.restore()
    assert t.policies[10] == {'policy': 1, 'priority': 20}


def test_existing_custom_policy_is_never_overwritten(setup):
    s,t = setup
    t.policies[11] = {'policy': 1, 'priority': 20}
    s.reconcile(True, CONFIG)
    assert not t.calls
    assert 'custom policy' in s.snapshot()['error']


def test_restart_adopts_journal_and_cleans_up_after_disable(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    new = RawScheduler(s.root, t)
    new.reconcile(True, CONFIG)
    assert new.snapshot()['active']
    assert len(t.calls) == 3
    new.enable_file.write_text('{"enabled":false}')
    new.reconcile(True, CONFIG)
    assert not new.snapshot()['active']
    assert all(p['policy'] == 0 for p in t.policies.values())


def test_old_boot_journal_is_discarded_without_touching_tasks(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    t.boot = 'next'
    t.calls.clear()
    s.restore()
    assert not t.calls


def test_thread_recreation_is_discovered_again(setup):
    s,t = setup
    s.reconcile(True, CONFIG)
    for row in t.rows:
        row['tid'] += 100
        row['start'] = '200'
        t.policies[row['tid']] = {'policy': 0, 'priority': 0}
    s.reconcile(True, CONFIG)
    assert s.snapshot()['active']
    assert [r['tid'] for r in s.snapshot()['workers']] == [110,111,112]


def test_unsupported_or_incomplete_workers_do_not_change_policy(setup):
    s,t = setup
    t.support = False
    s.reconcile(True, CONFIG)
    assert not t.calls
    t.support = True
    t.rows = []
    s.reconcile(True, CONFIG)
    assert not t.calls
    assert 'Waiting' in s.snapshot()['error']


def test_corrupt_journal_is_retained_and_refuses_changes(setup):
    s,t = setup
    s.file.write_text(json.dumps({'version':1,'workers':[]}))
    s.reconcile(True, CONFIG)
    assert 'Invalid' in s.snapshot()['error']
    assert s.file.exists()
    assert not t.calls
