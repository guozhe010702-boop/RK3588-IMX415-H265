"""ADB acceptance runner; JSON reports distinguish synthetic codec and camera tests."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
REMOTE = '/userdata/av_dev/ffmpeg_pipeline/avctl.py'
ADB = ROOT.parent / 'Tools/platform-tools/adb.exe'


def command(action, config=None):
    remote_file = None
    try:
        remote_command = 'python3 ' + REMOTE + ' ' + action
        if config is not None:
            remote_file = '/userdata/av_dev/ffmpeg_pipeline/state/acceptance-' + uuid.uuid4().hex + '.json'
            with tempfile.TemporaryDirectory() as directory:
                local = Path(directory) / 'config.json'
                local.write_text(json.dumps(config), encoding='utf-8')
                subprocess.run([str(ADB), 'push', str(local), remote_file], check=True, capture_output=True, timeout=10)
            remote_command += ' --config-stdin < ' + remote_file
        response = subprocess.run([str(ADB), 'shell', remote_command],
                                  capture_output=True, text=True, timeout=90)
    finally:
        if remote_file:
            subprocess.run([str(ADB), 'shell', 'rm -f ' + remote_file], capture_output=True, timeout=10)
    value = json.loads(response.stdout)
    if not value.get('ok'):
        raise RuntimeError(str(value))
    return value['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--cycles', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = command('status')
    if original.get('recording'):
        raise SystemExit('Recording active; acceptance refuses to change parameters')
    config = dict(original.get('config', {}), width=3840, height=2160, fps=30,
                  codec='h265', bitrate=20000000, gop=30)
    result = {'scope': 'REAL_CAMERA_4K30_NOT_4K60', 'real4k60Validated': False,
              'configuration': config, 'original': original.get('config'), 'cycles': [], 'samples': []}
    try:
        command('start', config)
        command('decode-start')
        for cycle in range(args.cycles):
            command('stop')
            state = command('start', config)
            command('decode-start')
            result['cycles'].append({'cycle': cycle + 1, 'pid': state['capturePid'], 'ready': state['rtspReady']})
        # Let decoder reach its first GOP and establish telemetry baselines.
        time.sleep(4)
        start = time.monotonic()
        with (args.output / 'board-samples.jsonl').open('w', encoding='utf-8') as out:
            while time.monotonic() - start < args.seconds:
                at = time.monotonic()
                state = command('status')
                out.write(json.dumps(state) + '\n')
                out.flush()
                m = state.get('metrics', {})
                result['samples'].append({'at': at, 'capture': m.get('capture'),
                    'frame': state.get('frame'), 'encoderFps': m.get('encoderFps'),
                    'decoder': m.get('decoder'), 'rtspMbps': m.get('rtspMbps'),
                    'state': state.get('state'), 'error': state.get('lastError')})
                if state.get('state') != 'running':
                    raise RuntimeError('Capture stopped during stability test')
                time.sleep(max(0, 1 - (time.monotonic() - at)))
        result['durationSeconds'] = time.monotonic() - start
        result['completed'] = True
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        try:
            command('stop')
            command('start', original.get('config'))
            command('decode-start')
            result['restoredDefault'] = True
        except Exception as error:
            result['restoreError'] = str(error)
        (args.output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
