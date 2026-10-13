import hashlib
import os
from pathlib import Path
import sys
import threading
import time
import pytest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from evm_console.core import Connection,load_preview_quality,save_preview_quality,save_preferences
from evm_console.files import copy_remote,FileWorker
from evm_console.ssh import SSHWorker
from evm_console.video import VideoWorker,preview_size
from evm_console.window import MainWindow
from test_core import SFTP

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

def pump(app,predicate,timeout=3):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:
        app.processEvents(); time.sleep(0.01)
    assert predicate()

def test_equal_size_existing_download_needs_matching_content(tmp_path):
    remote='/userdata/av_dev/ffmpeg_pipeline/recordings/a.mp4'
    existing=tmp_path/'a.mp4'; existing.write_bytes(b'xxxxxx')
    expected=hashlib.sha256(b'abcdef').hexdigest()
    with pytest.raises(ValueError): copy_remote(SFTP(),remote,tmp_path,threading.Event(),lambda *_:None,expected)
    assert existing.read_bytes()==b'xxxxxx'
    existing.write_bytes(b'abcdef')
    assert copy_remote(SFTP(),remote,tmp_path,threading.Event(),lambda *_:None,expected)==str(existing)

def test_checksum_failure_removes_partial_without_publishing(tmp_path):
    remote='/userdata/av_dev/ffmpeg_pipeline/recordings/a.mp4'
    with pytest.raises(ValueError,match='SHA-256'):
        copy_remote(SFTP(),remote,tmp_path,threading.Event(),lambda *_:None,'0'*64)
    assert not list(tmp_path.iterdir())

def test_windows_reserved_filename_rejected(tmp_path):
    with pytest.raises(ValueError):
        copy_remote(SFTP(),'/userdata/av_dev/ffmpeg_pipeline/recordings/CON.mp4',tmp_path,threading.Event(),lambda *_:None)

def test_profile_persistence_and_aspect_ratio(tmp_path,monkeypatch):
    monkeypatch.setenv('EVM_CONSOLE_DATA',str(tmp_path))
    save_preview_quality('均衡'); save_preferences(Connection(),tmp_path,False)
    assert load_preview_quality()=='均衡'
    assert preview_size(1920,1080,960)==(960,540)
    assert preview_size(1280,1024,640)==(640,512)
    with pytest.raises(ValueError): preview_size(0,1080,640)

def test_old_control_and_file_jobs_are_invalidated():
    ssh=SSHWorker(); emitted=[]
    ssh.submit('connect',(Connection(),'secret')); old=ssh.generation
    ssh.submit('record-start'); ssh.submit('disconnect')
    from types import SimpleNamespace
    ssh.publish(SimpleNamespace(emit=lambda *args:emitted.append(args)),old,True)
    assert not emitted
    assert ssh.jobs.get()[0]!=ssh.generation
    files=FileWorker(); files.configure(Connection(),'secret'); files.submit('download',('a.mp4','folder'))
    files.disconnect()
    assert files.jobs.get()[0]!=files.generation

def test_decoder_failure_keeps_worker_alive_and_exits(app,monkeypatch):
    import evm_console.video as video
    monkeypatch.setattr(video,'executable',lambda _:(_ for _ in ()).throw(FileNotFoundError('test missing ffmpeg')))
    worker=VideoWorker(); worker.configure('rtsp://localhost/test',1920,1080,('test',))
    worker.start(); pump(app,lambda:worker.isRunning())
    time.sleep(0.15); worker.shutdown()
    assert worker.wait(3000)
    assert worker.pid is None and worker.latest is None

def test_close_is_nonblocking_and_logs_are_batched(app,tmp_path,monkeypatch):
    monkeypatch.setenv('EVM_CONSOLE_DATA',str(tmp_path))
    window=MainWindow(); window.show()
    for index in range(300): window.add_log('播放',f'event {index}')
    assert window.log_view.toPlainText()==''
    window.flush_logs()
    assert 'event 299' in window.log_view.toPlainText()
    for worker in (window.ssh,window.video,window.files):
        monkeypatch.setattr(worker,'wait',lambda *_:(_ for _ in ()).throw(AssertionError('GUI must not wait')))
    began=time.monotonic(); window.close()
    assert time.monotonic()-began<0.3
    pump(app,lambda:not window.isVisible())
    assert not any(worker.isRunning() for worker in (window.ssh,window.video,window.files))

def test_file_worker_survives_transport_cleanup_failure(app,monkeypatch):
    import evm_console.files as files
    from types import SimpleNamespace
    attempts=[]; listings=[]
    class Session:
        def __init__(self): self.broken=not attempts; attempts.append(self)
        def open_sftp(self): return self
        def get_channel(self): return SimpleNamespace(settimeout=lambda _:None)
        def listdir_attr(self,_):
            if self.broken: raise EOFError('lost transport')
            return []
        def close(self):
            if self.broken: raise EOFError('close failed after disconnect')
    monkeypatch.setattr(files,'connect_ssh',lambda *_:Session())
    worker=FileWorker(); worker.configure(Connection(),''); worker.listing.connect(listings.append)
    worker.submit('list'); worker.submit('list'); worker.start()
    try:
        pump(app,lambda:bool(listings))
        assert listings==[[]] and len(attempts)==2 and worker.isRunning()
    finally:
        worker.shutdown(); assert worker.wait(3000)
