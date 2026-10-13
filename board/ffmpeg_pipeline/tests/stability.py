"""30-minute live monitor; writes runtime evidence without changing settings."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=int,default=1800)
args=parser.parse_args()
assert args.seconds>=1
output=ROOT/'build/stability-samples.jsonl'
errors=[]; rows=[]; begin=time.monotonic(); started=time.strftime('%Y-%m-%dT%H:%M:%S%z')
ticks=os.sysconf(os.sysconf_names['SC_CLK_TCK']); previous=None
with output.open('w') as log:
    while True:
        now=time.monotonic()
        result=subprocess.run(['python3',str(ROOT/'avctl.py'),'status'],capture_output=True,text=True,timeout=10)
        data=json.loads(result.stdout)['result']
        row={'elapsedSeconds':round(now-begin,3),'state':data['state'],'pid':data['capturePid'],'frame':data['frame'],
             'frameAge':data['lastFrameAgeSeconds'],'vpu':data['vpuDeviceOpen'],'preview':data['previewRunning'],
             'readers':data['readers'],'duplicates':data['duplicateFrames'],'drops':data['droppedFrames']}
        if data['state']!='running' or not data['vpuDeviceOpen'] or not data['previewRunning']:
            errors.append(row)
        if row['pid']:
            stats=Path('/proc/{}/stat'.format(row['pid'])).read_text().split()
            cpu_ticks=int(stats[13])+int(stats[14]); rss=int(stats[23])*os.sysconf('SC_PAGE_SIZE')
            row['rssBytes']=rss
            if previous and previous['pid']==row['pid']:
                dt=now-previous['time']
                row['cpuPercent']=round((cpu_ticks-previous['ticks'])/ticks/dt*100,2)
                row['intervalFps']=round((row['frame']-previous['frame'])/dt,3)
                if row['frame']<=previous['frame'] or row['frameAge']>3.5: errors.append(row)
            elif previous: errors.append({'message':'Encoder restarted during steady-state test','row':row})
            previous={'time':now,'pid':row['pid'],'ticks':cpu_ticks,'frame':row['frame']}
        rows.append(row); log.write(json.dumps(row)+'\n'); log.flush()
        if now-begin>=args.seconds: break
        time.sleep(min(5,max(0.05,args.seconds-(time.monotonic()-begin))))
values=lambda key:[row[key] for row in rows if key in row]
report={'ok':not errors,'startedAt':started,'finishedAt':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'durationSeconds':round(time.monotonic()-begin,3),'samples':len(rows),'errors':errors,
        'framesAdvanced':rows[-1]['frame']-rows[0]['frame'],'cpuPercent':{'min':min(values('cpuPercent')),'max':max(values('cpuPercent'))},
        'rssBytes':{'min':min(values('rssBytes')),'max':max(values('rssBytes'))},
        'intervalFps':{'min':min(values('intervalFps')),'max':max(values('intervalFps'))},'final':rows[-1]}
(ROOT/'build/stability-result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
raise SystemExit(0 if report['ok'] else 1)
