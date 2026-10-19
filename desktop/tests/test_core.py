import json
import stat
import threading
from pathlib import Path
import io
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evm_console.core import FrameAssembler,Connection,parse_response,controls,save_preferences
from evm_console.files import copy_remote,checked_remote
from evm_console.core import four_k60_note


def test_4k60_note_distinguishes_mode_enumeration_and_acceptance():
    assert '待驱动适配' in four_k60_note({})
    available = {'sensorFramesPerSecond': 60, 'cameraCapabilities': {'fourK60': {
        'state': 'mode-available-unvalidated', 'verified': False}}}
    assert '完整验收尚未通过' in four_k60_note(available)
    available['cameraCapabilities']['fourK60']['verified'] = True
    assert '30 分钟全链路验收通过' in four_k60_note(available)

def test_response_validation():
    assert parse_response('{"ok":true,"result":{"state":"running"}}')['result']['state']=='running'
    for value in ['[]','{"ok":1}','{"ok":true,"result":[]}']:
        with pytest.raises(ValueError): parse_response(value)
    assert not parse_response('{"ok":false,"error":"failed"}')['ok']

def test_frame_assembler_handles_fragments_and_keeps_latest():
    frames=FrameAssembler(6)
    assert frames.feed(b'abc') is None
    assert frames.feed(b'defghijklmn')==b'ghijkl'
    assert frames.feed(b'opqr')==b'mnopqr'
    assert len(frames.buffer)==0

def test_recording_disables_config_and_duplicate_start():
    state=controls({'state':'running','recording':True},True,False)
    assert state['record-stop'] and state['snapshot']
    assert not state['record-start'] and not state['apply']
    assert not any(controls({'state':'running'},False,False).values())
    assert not any(controls({'state':'running'},True,True).values())

def test_preferences_never_write_password(tmp_path,monkeypatch):
    monkeypatch.setenv('EVM_CONSOLE_DATA',str(tmp_path))
    save_preferences(Connection(),str(tmp_path/'videos'),True)
    data=json.loads((tmp_path/'preferences.json').read_text())
    assert set(data['connection'])=={'host','port','username','auth','key_file','remember'}

class SFTP:
    def __init__(self,data=b'abcdef',link=None): self.data=data; self.link=link
    def normalize(self,path): return self.link or path
    def lstat(self,path): return SimpleNamespace(st_mode=stat.S_IFREG,st_size=len(self.data))
    def stat(self,path): return self.lstat(path)
    def open(self,path,mode):
        class File(io.BytesIO):
            def prefetch(self,*args,**kwargs): pass
        return File(self.data)

def test_download_paths_and_links():
    for name in ['/etc/passwd','/userdata/av_dev/ffmpeg_pipeline/recordings/a.partial.mp4','/userdata/av_dev/ffmpeg_pipeline/recordings/../x.mp4']:
        with pytest.raises(ValueError): checked_remote(SFTP(),name)
    with pytest.raises(ValueError): checked_remote(SFTP(link='/tmp/a.mp4'),'/userdata/av_dev/ffmpeg_pipeline/recordings/a.mp4')

def test_download_completes_and_cancel_cleans_partial(tmp_path):
    path='/userdata/av_dev/ffmpeg_pipeline/recordings/a.mp4'; cancel=threading.Event()
    assert Path(copy_remote(SFTP(),path,tmp_path,cancel,lambda *_:None)).read_bytes()==b'abcdef'
    cancel.set()
    with pytest.raises(InterruptedError): copy_remote(SFTP(),path,tmp_path/'other',cancel,lambda *_:None)
    assert not list((tmp_path/'other').glob('*.part'))
