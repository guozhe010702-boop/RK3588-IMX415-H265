from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.validation import assess_record, read_acceptance


def record():
    return dict(schemaVersion=1, bootSha256='boot', kernelVersion='kernel', device='/dev/video44',
                scope='REAL_CAMERA_4K60_LAN_30MIN', completed=True, durationSeconds=1800,
                counterWindowSeconds=1799, captureFps=60, encoderFps=60, boardDecodeFps=60,
                pcDecodeFps=60, qtPaintFps=59.8, additionalSequenceGaps=0, captureErrors=0,
                duplicateFrames=0, droppedFrames=0, pcDecodeErrorsAfterWarmup=0)


def test_valid_real_camera_record_is_bound_to_running_system():
    assert assess_record(record(), 'boot', 'kernel', True)
    assert not assess_record(record(), 'other boot', 'kernel', True)
    assert not assess_record(record(), 'boot', 'other kernel', True)
    assert not assess_record(record(), 'boot', 'kernel', False)


def test_partial_synthetic_duplicate_and_invalid_values_never_pass():
    mutations = dict(schemaVersion=True, scope='SYNTHETIC', durationSeconds=60, counterWindowSeconds=60,
                     captureFps=30, encoderFps=float('nan'), pcDecodeFps=float('inf'),
                     qtPaintFps=40, duplicateFrames=1, captureErrors=1,
                     additionalSequenceGaps=1, completed=1, droppedFrames=True)
    for field, value in mutations.items():
        assert not assess_record(dict(record(), **{field: value}), 'boot', 'kernel', True), field
    for field in record():
        value = record();del value[field]
        assert not assess_record(value, 'boot', 'kernel', True), field


def test_enumeration_without_record_never_means_acceptance(tmp_path):
    assert read_acceptance(tmp_path/'absent', '/dev/video44', True)['state'] == 'mode-available-unvalidated'
    assert not read_acceptance(tmp_path/'absent', '/dev/video44', True)['verified']
    assert read_acceptance(tmp_path/'absent', '/dev/video44', False)['state'] == 'pending-driver'
