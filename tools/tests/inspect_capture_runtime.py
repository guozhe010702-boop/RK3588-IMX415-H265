"""Read-only board capture diagnostics, saved locally through the existing ADB."""
import argparse
import base64
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ADB = ROOT.parent / "Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe"
CODE = """
import json,subprocess
from pathlib import Path
root=Path('/userdata/av_dev/ffmpeg_pipeline')
def run(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=15)
    return {'code':p.returncode,'out':p.stdout,'err':p.stderr}
s=json.loads(run(['python3',str(root/'avctl.py'),'status'])['out'])
pid=s.get('result',{}).get('capturePid')
source=root/'build/ffmpeg/fftools/ffmpeg_demux.c'
print(json.dumps({'status':s,'cmdline':Path('/proc/'+str(pid)+'/cmdline').read_bytes().replace(b'\\0',b' ').decode() if pid else None,
    'demuxQueueSource':[l for l in source.read_text().splitlines() if any(t in l for t in ['thread_queue','queue_size','DEFAULT_'])],
    'memory':Path('/proc/meminfo').read_text(),
    'cameraProc':{p.name:p.read_text() for p in [Path('/proc/rkcif-mipi-lvds'),Path('/proc/rkisp0-vir0')] if p.is_file()},
    'interrupts':Path('/proc/interrupts').read_text(),
    'cameraAffinity':{p.parent.name:p.read_text().strip() for p in Path('/proc/irq').glob('*/smp_affinity_list')
        if p.parent.name in ['62','63','70']},
    'cameraDebug':run(['cat','/proc/rkisp-vir0']),
    'journal':run(['journalctl','-k','-b','--no-pager','-n','160'])}))
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    command = "python3 -c 'import base64;exec(base64.b64decode(\"" + base64.b64encode(CODE.encode()).decode() + "\"))'"
    data = json.loads(subprocess.check_output([str(ADB), "shell", command], timeout=40))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in data.items() if k not in ("status", "journal", "memory", "cameraProc", "interrupts")}))
    print(json.dumps({"capture": data["status"]["result"]["metrics"]["capture"]}))


if __name__ == "__main__":
    main()
