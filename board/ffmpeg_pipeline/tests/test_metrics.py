from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.metrics import Rates, session_rates, BoardMetrics
from camera_control.controller import Controller
from camera_control import transport


def test_session_match_excludes_hdmi_recordings_and_others():
    rates = Rates()
    rows = [{'id': '1', 'path': 'imx415', 'state': 'read', 'query': 'console='+'a'*32, 'outboundBytes': 0},
            {'id': '2', 'path': 'imx415', 'state': 'read', 'query': 'role=hdmi', 'outboundBytes': 100},
            {'id': '3', 'path': 'other', 'state': 'read', 'query': 'console='+'a'*32, 'outboundBytes': 100}]
    assert len(session_rates(rows, rates, 1)) == 1
    rows[0]['outboundBytes'] = 2500000
    assert session_rates(rows, rates, 2)[0]['mbps'] == 20
    rows[0]['id'] = 'reconnected'
    assert session_rates(rows, rates, 3)[0]['mbps'] is None
    assert len(rates.previous) == 1
    session_rates([], rates, 4)
    assert not rates.previous


def test_counter_monotonic_reset_and_missing():
    rates = Rates()
    assert rates.delta('frame', 1, 100, 5) is None
    assert rates.delta('frame', 1, 220, 7) == 60
    assert rates.delta('frame', 2, 280, 8) is None
    assert rates.delta('frame', 2, 0, 9) is None
    assert rates.delta('frame', 2, None, 10) is None


def test_stale_socket_is_stopped_service_not_failed_ssh(tmp_path):
    (tmp_path / 'state').mkdir()
    (tmp_path / 'state/control.sock').touch()
    client = MagicMock()
    client.__enter__.return_value.connect.side_effect = ConnectionRefusedError
    with patch.object(transport, 'ROOT', tmp_path), patch.object(socket, 'AF_UNIX', 1, create=True), patch.object(socket, 'socket', return_value=client):
        result = transport.request('status', {})
    assert result['ok'] and result['result']['state'] == 'stopped'
    assert result['result']['serviceRunning'] is False


def test_decoder_failure_does_not_stop_encoder(tmp_path):
    c = Controller(tmp_path)
    c.capture = object()
    with patch.object(c, 'status', return_value={'state': 'running'}), patch.object(
            c.decoder, 'start', side_effect=RuntimeError('RGA unavailable')):
        import pytest
        with pytest.raises(RuntimeError, match='RGA'):
            c.preview_start()
    assert c.capture is not None


def test_metrics_empty_is_stale(tmp_path):
    c = Controller(tmp_path)
    assert c.telemetry.snapshot()['stale']


def test_unknown_sensor_mapping_never_claims_60fps(tmp_path):
    import pytest
    from camera_control import controller
    c = Controller(tmp_path)
    with patch.object(controller, 'sensor_frame_rate', return_value=None), patch.object(c, 'stop_child') as stop:
        with pytest.raises(controller.ControlError, match='Cannot verify'):
            c.start({'device': '/dev/video45', 'fps': 60})
    stop.assert_not_called()
