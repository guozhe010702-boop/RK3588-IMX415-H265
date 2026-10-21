import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("start_hdmi", HERE / "start_8k_hdmi.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def test_one_command_launches_live_real_encoder_without_pc_preview(tmp_path):
    args = app.source_command(tmp_path, handover=False)
    assert "imx415_8k.py" in args[1]
    assert args[args.index("--mode") + 1] == "encode30"
    assert "--rtsp" in args and "--live" in args
    assert "--handover" not in args and "ffplay" not in args
    assert args[args.index("--output") + 1] == str(tmp_path / "evidence")


def test_encoder_handover_is_explicit(tmp_path):
    assert "--handover" in app.source_command(tmp_path, handover=True)


def test_stopping_uses_owned_worker_stop_file(tmp_path):
    process = Mock()
    process.poll.return_value = None
    stop = tmp_path / "evidence/stop.request"
    app.stop_owned(process, stop)
    assert stop.is_file()
    process.wait.assert_called_once_with(timeout=35)
    process.terminate.assert_not_called()


def test_borrowed_source_is_not_stopped(tmp_path):
    app.stop_owned(None, tmp_path / "borrowed/stop.request")
    assert not (tmp_path / "borrowed").exists()


def test_ready_source_requires_frames_and_not_only_process_liveness(tmp_path, monkeypatch):
    folder = tmp_path / "evidence"
    folder.mkdir()
    (folder / "progress.jsonl").write_text('{"frame": 20}\n')
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(app, "discover_capture", lambda: (123, folder))
    assert app.wait_source(process, tmp_path, [False]) == (123, folder)


def test_early_encoder_exit_reports_its_log(tmp_path):
    import pytest

    process = Mock()
    process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="source-worker.log"):
        app.wait_source(process, tmp_path, [False])


def test_borrowed_source_survives_hdmi_window_close(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ROOT", tmp_path)
    borrowed = tmp_path / "borrowed"
    borrowed.mkdir()
    monkeypatch.setattr(app, "discover_capture", lambda: (123, borrowed))
    hdmi = SimpleNamespace(pid=124, returncode=0, poll=lambda: 0)
    launch = Mock(return_value=hdmi)
    monkeypatch.setattr(app.subprocess, "Popen", launch)
    output = tmp_path / "session"
    assert app.run(output, 0, False, [False]) == 0
    assert launch.call_count == 1
    assert launch.call_args.args[0][1].endswith("hdmi_8k.py")
    assert not (borrowed / "stop.request").exists()
    import json

    assert json.loads((output / "session.json").read_text())["ownsSource"] is False


def test_startup_failure_cleans_only_the_new_source(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(app, "discover_capture", lambda: None)
    source = SimpleNamespace(
        pid=123, returncode=0, poll=lambda: None, wait=Mock(), terminate=Mock()
    )
    launch = Mock(return_value=source)
    monkeypatch.setattr(app.subprocess, "Popen", launch)
    monkeypatch.setattr(app, "wait_source", Mock(side_effect=RuntimeError("startup failed")))
    output = tmp_path / "session"
    with pytest.raises(RuntimeError, match="startup failed"):
        app.run(output, 0, False, [False])
    assert launch.call_count == 1
    assert (output / "evidence/stop.request").exists()
    source.wait.assert_called_once()
    assert not (output / "hdmi/stop.request").exists()
