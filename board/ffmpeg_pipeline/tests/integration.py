"""Live hardware acceptance: invoke after the first manual recording has run."""
import json
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
def call(action,config=None,expect=True):
    args=['python3',str(ROOT/'avctl.py'),action]
    if config is not None: args.append('--config-stdin')
    done=subprocess.run(args,input=json.dumps(config) if config is not None else None,capture_output=True,text=True,timeout=35)
    result=json.loads(done.stdout)
    assert result['ok']==expect,result
    return result.get('result',result)

report={'startedAt':time.strftime('%Y-%m-%dT%H:%M:%S%z')}
before=call('status')
assert before['recording'] and before['rtspReady'],before
call('start',dict(before['config'],bitrate=4000000),expect=False)
assert call('status')['capturePid']==before['capturePid']
report['recording']=call('record-stop')['lastRecording']
assert call('status')['capturePid']==before['capturePid'], 'Recording stop interrupted live encoder'
assert float(report['recording']['probe']['format']['duration'])>=60
report['stopStart']=[]
for index in range(10):
    call('stop')
    owners=subprocess.run(['lsof','-t','/dev/video44'],capture_output=True,text=True).stdout.strip()
    assert not owners,owners
    start=time.monotonic()
    state=call('start')
    seconds=time.monotonic()-start
    assert seconds<5 and state['vpuDeviceOpen'] and state['rtspReady'],state
    initial=state['frame']; time.sleep(1.1)
    assert call('status')['frame']>initial
    report['stopStart'].append({'iteration':index+1,'readySeconds':round(seconds,3)})
    print('Start/stop {}/10 passed'.format(index+1),flush=True)
call('preview-start')
old=call('status')['capturePid']
start=time.monotonic()
subprocess.run(['systemctl','restart','evm-mediamtx'],check=True)
while time.monotonic()-start<15:
    state=call('status')
    if state['state']=='running' and state['capturePid']!=old: break
    time.sleep(0.1)
else: raise AssertionError('Stream did not recover after RTSP restart')
seconds=time.monotonic()-start
assert seconds<5,seconds
report['rtspRestartReadySeconds']=round(seconds,3)
deadline=time.monotonic()+8
while not call('status')['previewRunning'] and time.monotonic()<deadline: time.sleep(0.2)
assert call('status')['previewRunning']
report['snapshot']=call('snapshot')
report['finishedAt']=time.strftime('%Y-%m-%dT%H:%M:%S%z')
(ROOT/'build/integration-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'ok':True,'result':report}),flush=True)
