from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evm_console.window import MainWindow

def dummy(recording=False):
    jobs=[]; errors=[]
    window=SimpleNamespace(pending_stop_recording=recording,
        auto_download=SimpleNamespace(isChecked=lambda:True),download_path=SimpleNamespace(text=lambda:'downloads'),
        files=SimpleNamespace(submit=lambda *job:jobs.append(job)),add_log=lambda *_:None,on_failure=lambda *error:errors.append(error))
    return window,jobs,errors

def test_stop_without_recording_does_not_download_old_file():
    window,jobs,_=dummy()
    MainWindow.on_result(window,'stop',{'ok':True,'result':{'recordingResult':{'lastRecording':{'file':'old.mp4'}}}})
    assert jobs==[('list',)]

def test_stop_with_recording_downloads_final_file():
    window,jobs,_=dummy(True)
    MainWindow.on_result(window,'stop',{'ok':True,'result':{'recordingResult':{'lastRecording':{'file':'new.mp4'}}}})
    assert ('download',('new.mp4','downloads')) in jobs

def test_nested_finalization_error_is_visible():
    window,jobs,errors=dummy(True)
    MainWindow.on_result(window,'stop',{'ok':True,'result':{'recordingResult':{'error':'partial retained'}}})
    assert errors and jobs==[('list',)]
