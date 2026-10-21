"""Verify original H.265 pipeline; --restore explicitly starts its saved defaults."""

import argparse
import json
from board_link import ROOT, remote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    code = """import sys,json,time,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,'/userdata/av_dev/ffmpeg_pipeline')
from camera_control.transport import request
config={'device':'/dev/video44','codec':'h265','width':3840,'height':2160,'fps':60,'bitrate':20000000,'gop':60}
def call(action,payload={}):
 r=request(action,payload)
 assert r.get('ok'),r
 return r['result']
if RESTORE:
 call('start',{'config':config})
 call('decode-start')
a=call('status');time.sleep(3);b=call('status')
assert b['state']=='running' and b['config']==config,b
assert b['previewRunning'] and b['rtspReady'] and b['vpuDeviceOpen'],b
assert int(b['frame'])>int(a['frame']),b
assert b['boardDecode']['frame']>a['boardDecode']['frame'],b
owners=[];leftovers=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  cmd=(p/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace')
  if cmd.startswith('./rknn_yolo_world_realtime ') or ('/ffmpeg ' in cmd and 'h264_rkmpp' in cmd):leftovers.append({'pid':int(p.name),'cmd':cmd})
  for fd in (p/'fd').glob('*'):
   try:
    if str(fd.resolve())=='/dev/video44':owners.append(int(p.name));break
   except OSError:pass
 except OSError:pass
assert not leftovers,leftovers
hashes={}
for name in ('mmcblk0p3','mmcblk0p1'):
 h=hashlib.sha256()
 with open('/dev/'+name,'rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 hashes[name]=h.hexdigest()
print(json.dumps({'state':b['state'],'config':b['config'],'encoder':b['encoder'],
 'rtspReady':b['rtspReady'],'hdmi':b['previewRunning'],'encoderFps':b['metrics'].get('encoderFps'),
 'decode':b['boardDecode'],'cameraOwners':owners,'detectionLeftovers':leftovers,'partitionHashes':hashes,
 'services':subprocess.getoutput('systemctl is-active rkaiq_3A.service evm-mediamtx.service evm-ffmpeg-control.service')}))
""".replace(
        "RESTORE", repr(args.restore)
    )
    data = json.loads(remote(code, timeout=40))
    expected = {
        "mmcblk0p3": "102a8af58b9bc0b6a5d542db4c41ca99b2dc0f4586776b67e78332836c1147c9",
        "mmcblk0p1": "7afde1f520b04124370c3dc7a4729a615f6ff85e4f1ff36ad63ac2a50877f84a",
    }
    assert data["partitionHashes"] == expected, data["partitionHashes"]
    (ROOT / "build/restoration-verification.json").write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
