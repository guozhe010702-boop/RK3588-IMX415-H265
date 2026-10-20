"""Read-only capture continuity test; never starts/stops/reconfigures the camera.

Run on the board after warm-up. Raw counters and every sample are retained,
including failures. A short run can be diagnostic but is not 30-min acceptance.
"""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.transport import request


def summarize(rows, required_seconds):
    a, b = rows[0], rows[-1]
    first, last = a['state'], b['state']
    ca, cb = first['metrics']['capture'], last['metrics']['capture']
    elapsed = b['monotonic'] - a['monotonic']
    reasons = []
    identity = (first.get('capturePid'), first.get('captureStartedAt'))
    previous_values = (None,) * 5
    for row in rows:
        s = row['state']; m = s.get('metrics', {}); c = m.get('capture', {})
        if ((s.get('capturePid'), s.get('captureStartedAt')) != identity
                or not identity[0] or s.get('config') != first.get('config')):
            reasons.append('Capture identity or configuration changed')
        age = s.get('lastFrameAgeSeconds')
        if (s.get('state') != 'running' or not s.get('rtspReady')
                or m.get('stale', True) or c.get('stale', True)
                or not c.get('available') or not isinstance(age, (int,float)) or age > 4):
            reasons.append('Stream stopped or telemetry became unavailable/stale')
        values = (c.get('frames'), s.get('frame'), c.get('sequenceGaps'), c.get('errors'), c.get('monotonicUs'))
        for current, previous in zip(values, previous_values):
            if not isinstance(current, (int,float)) or (previous is not None and current < previous):
                reasons.append('Counter unavailable or reset inside the test window')
        previous_values = values
    capture_time = (cb['monotonicUs'] - ca['monotonicUs']) / 1e6
    fps = (cb['frames'] - ca['frames']) / capture_time if capture_time > 0 else None
    gaps, errors = cb['sequenceGaps'] - ca['sequenceGaps'], cb['errors'] - ca['errors']
    if gaps: reasons.append('New capture sequence gaps')
    if errors: reasons.append('New capture error buffers')
    if elapsed < required_seconds: reasons.append('Requested observation duration not reached')
    target = first['config']['fps']
    if fps is None or fps < target * 59 / 60:
        reasons.append('Capture average below target threshold')
    # The progress frame counter can be almost one second older than the SSH
    # sample. Use its measured age to align the two counter observations;
    # otherwise a short window can incorrectly report >60 fps for a 60 fps stream.
    ages = (first.get('lastFrameAgeSeconds'), last.get('lastFrameAgeSeconds'))
    encode_elapsed = (elapsed + ages[0] - ages[1]
                      if all(isinstance(v, (int,float)) for v in ages) else None)
    for key in ('droppedFrames', 'duplicateFrames'):
        try:
            if int(last[key]) != int(first[key]): reasons.append('Encoder '+key+' changed')
        except (ValueError, TypeError, KeyError):
            reasons.append('Encoder '+key+' unavailable')
    return {'scope': 'BOARD_CAPTURE_CONTINUITY_ONLY', 'passed': not reasons,
            'fullChain4k60Validated': False, 'requestedSeconds': required_seconds,
            'durationSeconds': elapsed, 'samples': len(rows), 'config': first['config'],
            'capturePid': first.get('capturePid'), 'captureFps': fps,
            'encodeFps': ((last['frame'] - first['frame']) / encode_elapsed
                          if encode_elapsed is not None and encode_elapsed > 0 else None),
            'encoderCounterIntervalSeconds': encode_elapsed,
            'newSequenceGaps': gaps, 'captureErrors': errors,
            'startSequenceGaps': ca['sequenceGaps'], 'endSequenceGaps': cb['sequenceGaps'],
            'failures': sorted(set(reasons)), 'first': first, 'last': last}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=1800)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 2:
        parser.error('--seconds must be at least 2')
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    start = time.monotonic()
    failure = None
    try:
        with (args.output/'samples.jsonl').open('w') as out:
            while True:
                at = time.monotonic()
                response = request('status', {})
                if not response.get('ok'):
                    raise RuntimeError(str(response))
                row = {'monotonic': time.monotonic(), 'state': response['result']}
                rows.append(row)
                out.write(json.dumps(row)+'\n'); out.flush()
                if row['monotonic'] - rows[0]['monotonic'] >= args.seconds:
                    break
                time.sleep(max(0, 1 - (time.monotonic()-at)))
    except Exception as error:
        failure = str(error)
    try:
        result = summarize(rows, args.seconds) if rows else {'passed': False}
    except (KeyError, TypeError, ValueError) as error:
        result = {'passed': False, 'error': 'Incomplete telemetry: '+str(error)}
    if failure:
        result.update(passed=False, error=failure)
    result['wallSeconds'] = time.monotonic()-start
    (args.output/'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ('first','last')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
