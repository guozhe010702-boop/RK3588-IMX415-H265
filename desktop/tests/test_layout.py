"""Regression for extracted layout-to-controller callbacks and credential startup."""

import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from evm_console.core import Connection, DEFAULT_CONFIG, save_preferences
from evm_console.window import MainWindow


def close_window(app, window):
    window.close()
    deadline = time.monotonic() + 3
    while (
        any(worker.isRunning() for worker in (window.ssh, window.video, window.files))
        and time.monotonic() < deadline
    ):
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not any(worker.isRunning() for worker in (window.ssh, window.video, window.files))


def test_extracted_layout_keeps_snapshot_callback(tmp_path, monkeypatch):
    monkeypatch.setenv("EVM_CONSOLE_DATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    jobs = []
    monkeypatch.setattr(window.ssh, "submit", lambda *args: jobs.append(args))
    try:
        window.ssh_connected = True
        window.board = {"state": "running", "config": DEFAULT_CONFIG}
        window.update_controls()
        window.action_buttons["snapshot"].click()
        assert jobs == [("snapshot",)] and window.operation_busy
        assert window.pages.count() == 4
    finally:
        close_window(app, window)


def test_saved_credential_is_restored_after_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("EVM_CONSOLE_DATA", str(tmp_path))
    save_preferences(Connection(remember=True), tmp_path, False)
    import evm_console.window as window_module

    monkeypatch.setattr(window_module.keyring, "get_password", lambda *_: "test-private-value")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.secret.text() == "test-private-value"
        assert "test-private-value" not in (tmp_path / "preferences.json").read_text()
    finally:
        close_window(app, window)
