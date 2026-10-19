"""Read a local acceptance record, bound to the running kernel and boot image.

Mode enumeration alone never passes acceptance. This module never creates a
record, changes a driver, starts a capture, or writes any block device.
"""
import hashlib
import json
import math
from pathlib import Path


def assess_record(record, boot_sha256, kernel_version, experimental_dt):
    if (not isinstance(record, dict) or type(record.get('schemaVersion')) is not int
            or record.get('schemaVersion') != 1):
        return False
    if (not boot_sha256 or not kernel_version or not experimental_dt
            or record.get('bootSha256') != boot_sha256
            or record.get('kernelVersion') != kernel_version
            or record.get('device') != '/dev/video44'
            or record.get('scope') != 'REAL_CAMERA_4K60_LAN_30MIN'
            or record.get('completed') is not True):
        return False

    def numeric(name, low, high):
        value = record.get(name)
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high

    return (numeric('durationSeconds', 1800, 86400)
            and numeric('counterWindowSeconds', 1790, 86400)
            and all(numeric(key, 59, 62) for key in
                    ['captureFps', 'encoderFps', 'boardDecodeFps', 'pcDecodeFps'])
            and numeric('qtPaintFps', 55, 62)
            and all(numeric(key, 0, 0) for key in
                    ['additionalSequenceGaps', 'captureErrors', 'duplicateFrames',
                     'droppedFrames', 'pcDecodeErrorsAfterWarmup']))


def read_acceptance(path, device, mode_available):
    result = {'verified': False, 'state': 'mode-available-unvalidated' if mode_available else 'pending-driver',
              'reason': '60 fps mode enumerated; full acceptance record required' if mode_available
                        else 'Sensor does not enumerate a 4K mode at >=59 fps'}
    if device != '/dev/video44' or not mode_available or not path.is_file():
        return result
    try:
        if path.stat().st_size > 65536:
            raise ValueError('Acceptance record too large')
        record = json.loads(path.read_text(encoding='utf-8'))
        kernel = Path('/proc/version').read_text().strip()
        flag = Path('/proc/device-tree/i2c@feaa0000/imx415@36/dvsense,experimental-4k60').is_file()
        digest = hashlib.sha256()
        with open('/dev/disk/by-partlabel/boot', 'rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
                digest.update(chunk)
        if not assess_record(record, digest.hexdigest(), kernel, flag):
            raise ValueError('Record does not pass all thresholds or match the running boot/kernel/DT')
        result.update(verified=True, state='validated', reason='Local real-camera LAN acceptance passed',
                      acceptance={key: record.get(key) for key in
                                  ['date', 'durationSeconds', 'captureFps', 'encoderFps',
                                   'boardDecodeFps', 'pcDecodeFps', 'qtPaintFps']})
    except (OSError, ValueError, TypeError, AttributeError) as error:
        result['recordError'] = str(error)
    return result
