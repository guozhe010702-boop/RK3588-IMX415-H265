#!/usr/bin/env python3
"""Guarded boot-only switch for this EVM3588 B1 candidate. Default: check only.

Never reboots or touches another partition. --apply / --restore-original require
separate operator authorization and a stopped camera pipeline.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

try:
    import fcntl
except ImportError:
    fcntl = None

SIZE = 67108864
TARGET = Path('/dev/mmcblk0p3')
LABEL = Path('/dev/disk/by-partlabel/boot')
BASE = Path('/userdata/av_dev/firmware_candidates/20261019-b1-v2')
CANDIDATE = BASE / 'boot-candidate-partition.img'
BACKUP = Path('/userdata/av_dev_backups/boot-pre-4k60-20261016.img')
OLD_SHA = '7cf5378f68e374aec8d2fe8b01e8ba4e8e36863a8b71f61ba670c5f6dc3bca7f'
NEW_SHA = '102a8af58b9bc0b6a5d542db4c41ca99b2dc0f4586776b67e78332836c1147c9'
UBOOT_SHA = '7afde1f520b04124370c3dc7a4729a615f6ff85e4f1ff36ad63ac2a50877f84a'


class SwitchError(RuntimeError):
    pass


def validate_identity(model, resolved, start, sectors):
    if model != 'Rockchip RK3588 EVM3588 B1 Board':
        raise SwitchError('Board model mismatch')
    if str(resolved) != str(TARGET) or start != 32768 or sectors != 131072:
        raise SwitchError('Boot partition identity/range mismatch')


def verify_blob(data, expected, size=SIZE):
    if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
        raise SwitchError('Image length or SHA-256 mismatch')
    return data


def hash_fd(fd, size):
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        data = os.read(fd, min(4 * 1024**2, remaining))
        if not data:
            raise SwitchError('Short partition read')
        digest.update(data)
        remaining -= len(data)
    return digest.hexdigest()


def flush_block(fd):
    # BLKFLSBUF: flush and invalidate only this raw, unmounted boot device.
    fcntl.ioctl(fd, 0x1261, 0)


def write_verified(fd, data, flush_cache=flush_block, writer=os.write):
    os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        count = writer(fd, view[offset:offset + 4 * 1024**2])
        if count <= 0:
            raise SwitchError('Zero-length partition write')
        offset += count
    os.fsync(fd)
    flush_cache(fd)
    if hash_fd(fd, len(data)) != hashlib.sha256(data).hexdigest():
        raise SwitchError('Full partition read-back mismatch')


def apply_transaction(fd, before, candidate, flush_cache=flush_block, writer=os.write):
    try:
        write_verified(fd, candidate, flush_cache, writer)
    except Exception as failure:
        try:
            write_verified(fd, before, flush_cache)
        except Exception as rollback_failure:
            raise SwitchError('Write and original-boot restoration failed; use Maskrom: {} / {}'.format(
                failure, rollback_failure)) from rollback_failure
        raise SwitchError('Candidate write failed; original boot restored and verified: {}'.format(failure)) from failure


def digest_file(path):
    with path.open('rb') as stream:
        # Block devices normally report st_size=0; use their actual seek range.
        size = os.lseek(stream.fileno(), 0, os.SEEK_END)
        return hash_fd(stream.fileno(), size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--restore-original', action='store_true')
    args = parser.parse_args()
    if fcntl is None or sys.platform != 'linux' or os.geteuid() != 0:
        raise SwitchError('Run on the actual Linux board as root')
    model = Path('/proc/device-tree/model').read_bytes().rstrip(b'\0').decode()
    validate_identity(model, LABEL.resolve(strict=True),
                      int(Path('/sys/class/block/mmcblk0p3/start').read_text()),
                      int(Path('/sys/class/block/mmcblk0p3/size').read_text()))
    if not stat.S_ISBLK(TARGET.stat().st_mode):
        raise SwitchError('Target is not a block device')
    if not BACKUP.is_file() or BACKUP.is_symlink():
        raise SwitchError('Missing regular original backup')
    original = verify_blob(BACKUP.read_bytes(), OLD_SHA)
    candidate = None
    if not args.restore_original:
        if not CANDIDATE.is_file() or CANDIDATE.is_symlink():
            raise SwitchError('Missing regular candidate file')
        candidate = verify_blob(CANDIDATE.read_bytes(), NEW_SHA)
    if digest_file(Path('/dev/disk/by-partlabel/uboot')) != UBOOT_SHA:
        raise SwitchError('U-Boot changed from the recovery baseline')
    status = subprocess.run(['python3', '/userdata/av_dev/ffmpeg_pipeline/avctl.py', 'status'],
                            capture_output=True, text=True, timeout=10)
    control = json.loads(status.stdout)
    if status.returncode or not control.get('ok'):
        raise SwitchError('Camera state unavailable')
    mutating = args.apply or args.restore_original
    if mutating and (control['result'].get('recording') or control['result'].get('state') != 'stopped'):
        raise SwitchError('Stop camera/recording before changing boot')
    flags = (os.O_RDWR if mutating else os.O_RDONLY) | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(str(TARGET), flags)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not stat.S_ISBLK(os.fstat(fd).st_mode) or os.fstat(fd).st_rdev != TARGET.stat().st_rdev:
            raise SwitchError('Opened device identity changed')
        if os.lseek(fd, 0, os.SEEK_END) != SIZE:
            raise SwitchError('Opened block device capacity mismatch')
        current = hash_fd(fd, SIZE)
        report = {'target': str(TARGET), 'bytes': SIZE, 'currentSha256': current,
                  'candidateSha256': NEW_SHA, 'originalSha256': OLD_SHA,
                  'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  'action': 'apply' if args.apply else 'restore-original' if args.restore_original else 'check',
                  'state': 'PREFLIGHT_PASSED', 'rebootRequested': False}
        record = BASE / ('boot-switch-' + report['action'] + '.json')
        record.write_text(json.dumps(report, indent=2) + '\n')
        if args.apply:
            if current != OLD_SHA:
                raise SwitchError('Current boot is not the approved original; do not repeat writes')
            apply_transaction(fd, original, candidate)
            report['state'] = 'CANDIDATE_WRITTEN_READBACK_VERIFIED_NOT_REBOOTED'
        elif args.restore_original:
            if current != OLD_SHA:
                write_verified(fd, original)
            report['state'] = 'ORIGINAL_BOOT_VERIFIED_NOT_REBOOTED'
        report['afterSha256'] = hash_fd(fd, SIZE)
        if digest_file(Path('/dev/disk/by-partlabel/uboot')) != UBOOT_SHA:
            raise SwitchError('Unexpected U-Boot hash change')
        record.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'ok': True, 'result': report}), flush=True)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}), flush=True)
        sys.exit(1)
