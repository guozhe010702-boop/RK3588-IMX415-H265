"""Read-only live GUI monitoring after the user has configured SSH access."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from evm_console.window import MainWindow
from evm_console.core import data_root

parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=int,default=1800); args=parser.parse_args()
if args.seconds<10: parser.error('--seconds must be at least 10')
app=QApplication([]); window=MainWindow(); window.setWindowTitle('相机控制台 · 只读运行验收'); window.show()
window.message.setText('先连接已有直播；出画面后开始计时，测试期间操作将禁用。')
started=None; last=0; initial=0; samples=[]; report={'errors':[]}; proc=psutil.Process()

def finish(error=None):
    if error: report['errors'].append(str(error))
    report.update(ok=not report['errors'],finishedAt=datetime.now().astimezone().isoformat(),samples=samples)
    if started: report.update(durationSeconds=round(time.monotonic()-started,3),frames=window.video.frames-initial)
    (data_root()/'live-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    timer.stop(); window.close()

def tick():
    global started,last,initial
    now=time.monotonic()
    if started is None:
        if window.ssh_connected and window.video.frames>10 and window.board.get('state')=='running':
            started=now; initial=window.video.frames; window.setEnabled(False)
            report['startedAt']=datetime.now().astimezone().isoformat()
        return
    if now-last>=5:
        row={'elapsedSeconds':round(now-started,3),'rssBytes':proc.memory_info().rss,'frames':window.video.frames-initial,
             'frameAge':round(now-window.video.last_frame,3),'capturePid':window.board.get('capturePid'),
             'ssh':window.ssh_connected,'running':window.board.get('state')=='running'}
        samples.append(row); last=now
        if not row['ssh'] or not row['running'] or row['frameAge']>4: finish(row); return
    if now-started>=args.seconds:
        if len(set(row['capturePid'] for row in samples))!=1: finish('Capture restarted during monitoring')
        else: finish()

timer=QTimer(); timer.setInterval(100); timer.timeout.connect(tick); timer.start(); app.exec()
if started is None: raise SystemExit('Test cancelled before preview was ready')
print(json.dumps({'ok':report.get('ok',False),'output':str(data_root()/'live-acceptance.json')}))
raise SystemExit(0 if report.get('ok') else 1)
