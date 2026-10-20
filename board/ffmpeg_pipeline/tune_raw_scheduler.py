"""Inspect or opt in to the RK3588 AIQ RAW scheduling trial; never writes firmware."""
import argparse
import json
from camera_control.config import ROOT
from camera_control.raw_scheduler import RawScheduler
from camera_control.support import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--enable', action='store_true')
    group.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    scheduler = RawScheduler(ROOT)
    if args.enable:
        if not scheduler.tasks.supported():
            raise RuntimeError('This trial is restricted to RK3588')
        atomic_json(scheduler.enable_file, {'enabled': True})
    elif args.disable:
        atomic_json(scheduler.enable_file, {'enabled': False})
        # The live controller owns applying/restoring policies; this process only
        # changes the opt-in file, avoiding two processes racing over a journal.
    print(json.dumps({'ok': True, 'enabled': scheduler.enable_file.exists() and
                     json.loads(scheduler.enable_file.read_text()).get('enabled') is True,
                     'journal': json.loads(scheduler.file.read_text()) if scheduler.file.exists() else None}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        raise SystemExit(1)
