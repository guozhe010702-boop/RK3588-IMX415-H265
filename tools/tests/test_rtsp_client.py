"""Measure reconnect-to-decoded-frame time on the PC (not glass-to-glass latency)."""
import argparse
import json
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='rtsp://192.168.2.221:8554/imx415')
parser.add_argument('--attempts',type=int,default=5)
args=parser.parse_args()
rows=[]
for i in range(args.attempts):
    start=time.perf_counter()
    result=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-rtsp_transport','tcp','-i',args.url,
                           '-map','0:v:0','-an','-frames:v','1','-f','null','-'],capture_output=True,timeout=8)
    elapsed=time.perf_counter()-start
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert elapsed<5,elapsed
    rows.append({'attempt':i+1,'decodedFrameSeconds':round(elapsed,3)})
print(json.dumps({'ok':True,'attempts':rows}))
