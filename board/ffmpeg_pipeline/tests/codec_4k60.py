#!/usr/bin/env python3
"""Synthetic VPU encode/decode throughput; never counts as camera validation."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = str(ROOT / 'runtime/bin/ffmpeg')
ENV = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'runtime/lib') + ':' + str(ROOT / 'runtime/lib64'))


def execute(arguments, output, name):
    started = time.monotonic()
    device_open = False
    with (output / (name + '.log')).open('w') as log, (output / (name + '-progress.log')).open('w') as progress:
        process = subprocess.Popen([FFMPEG, '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
            '-stats_period', '1', '-progress', 'pipe:1'] + arguments,
            env=ENV, stdout=progress, stderr=log, stdin=subprocess.DEVNULL)
        while process.poll() is None:
            for fd in Path('/proc/{}/fd'.format(process.pid)).glob('*'):
                try:
                    device_open |= os.readlink(str(fd)) in ('/dev/mpp_service', '/dev/mpp-service', '/dev/rkvenc', '/dev/rkvdec')
                except OSError:
                    pass
            if time.monotonic() - started > 120:
                process.kill()
                process.wait()
                raise RuntimeError(name + ' exceeded 120 seconds')
            time.sleep(0.05)
    elapsed = time.monotonic() - started
    frames = re.findall(r'^frame=(\d+)', (output / (name + '-progress.log')).read_text(), re.M)
    count = int(frames[-1]) if frames else 0
    return {'exitCode': process.returncode, 'frames': count, 'wallSeconds': elapsed,
            'framesPerWallSecond': count / elapsed, 'mppDeviceObserved': device_open}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    movie = args.output / 'synthetic-4k60.mp4'
    result = {'scope': 'SYNTHETIC_CODEC_ONLY', 'real4k60Validated': False, 'requestedFrames': args.frames}
    result['encode'] = execute(['-f', 'lavfi', '-i', 'testsrc2=size=3840x2160:rate=60',
        '-frames:v', str(args.frames), '-vf', 'format=nv12', '-an', '-c:v', 'hevc_rkmpp',
        '-rc_mode', 'CBR', '-b:v', '20M', '-g', '60', '-bf', '0', '-fps_mode', 'passthrough',
        '-tag:v', 'hvc1', '-y', str(movie)], args.output, 'encode')
    if result['encode']['exitCode'] == 0:
        result['decode'] = execute(['-hwaccel', 'rkmpp', '-hwaccel_output_format', 'drm_prime',
            '-c:v', 'hevc_rkmpp', '-i', str(movie), '-an',
            '-vf', 'scale_rkrga=w=1920:h=1080:format=nv12,hwdownload,format=nv12',
            '-fps_mode', 'passthrough', '-f', 'null', '-'], args.output, 'decode')
        probe = subprocess.run([str(ROOT / 'runtime/bin/ffprobe'), '-v', 'error', '-count_frames',
            '-show_entries', 'stream=codec_name,width,height,r_frame_rate,nb_read_frames', '-of', 'json', str(movie)],
            env=ENV, capture_output=True, text=True, timeout=60)
        result['probe'] = json.loads(probe.stdout)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
