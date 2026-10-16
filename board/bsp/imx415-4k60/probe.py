#!/usr/bin/env python3
"""Read-only BSP evidence. Does not set controls, stream, reboot or write /boot."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def run(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=8)
        return {'exitCode': r.returncode, 'stdout': r.stdout[-40000:], 'stderr': r.stderr[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'error': str(error)}


def collect():
    result = {name: run(command) for name, command in {
        'kernel': ['uname', '-a'], 'model': ['cat', '/proc/device-tree/model'],
        'sensorFormat': ['v4l2-ctl', '-d', '/dev/v4l-subdev2', '--get-subdev-fmt', '0'],
        'sensorFps': ['v4l2-ctl', '-d', '/dev/v4l-subdev2', '--get-subdev-fps'],
        'sensorControls': ['v4l2-ctl', '-d', '/dev/v4l-subdev2', '-L'],
        'sensorIntervals': ['v4l2-ctl', '-d', '/dev/v4l-subdev2', '--list-subdev-frameintervals',
                            'pad=0,code=0x300e,width=3864,height=2192'],
        'clockTree': ['cat', '/sys/kernel/debug/clk/clk_summary'],
        'captureFormat': ['v4l2-ctl', '-d', '/dev/video44', '--get-fmt-video-mplane'],
        'partitions': ['lsblk', '-o', 'NAME,SIZE,FSTYPE,MOUNTPOINT,PARTLABEL'],
        'bootCommand': ['cat', '/proc/cmdline'],
    }.items()}
    boot = []
    for path in Path('/boot').rglob('*'):
        if path.is_file() and path.stat().st_size < 200 * 1024**2:
            boot.append({'path': str(path), 'bytes': path.stat().st_size,
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    result['bootFiles'] = boot
    result['dtSensor'] = {}
    for path in Path('/sys/firmware/devicetree/base').glob('i2c*/imx415*/*'):
        if path.is_file():
            result['dtSensor'][str(path)] = path.read_bytes().hex()
    result['status'] = 'evidence-only-not-4k60-validation'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(collect(), indent=2)
    if args.output:
        args.output.write_text(text + '\n')
    else:
        print(text)
