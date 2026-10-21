"""Start the board-owned test wrapper; it saves/restores the existing pipeline."""

import argparse, json
from board_link import ROOT, remote, push


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--hdmi", action="store_true")
    a = p.parse_args()
    dest = "/userdata/rk-yoloworld"
    remote("import os;os.makedirs('" + dest + "/tools',exist_ok=True)")
    for src, target in [
        (ROOT / "dist/rknn_yolo_world_realtime", "rknn_yolo_world_realtime"),
        (ROOT / "run_realtime_yolo_world.sh", "run_realtime_yolo_world.sh"),
        (ROOT / "config.env", "config.env"),
        (ROOT / "tools/run_with_restore.py", "tools/run_with_restore.py"),
        (ROOT / "tools/hdmi_preview.py", "tools/hdmi_preview.py"),
        (ROOT / "tools/monitor.py", "tools/monitor.py"),
    ]:
        push(src, dest + "/" + target)
    code = """import os,subprocess,json
from pathlib import Path
root=Path('/userdata/rk-yoloworld');(root/'state').mkdir(exist_ok=True)
os.chmod(root/'rknn_yolo_world_realtime',0o755)
out=open(root/'state/test-wrapper.log','w')
p=subprocess.Popen(['python3',str(root/'tools/run_with_restore.py'),'--seconds',SECONDS]+EXTRA,cwd=str(root),stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
(root/'state/test-wrapper.pid').write_text(str(p.pid))
print(json.dumps({'wrapperPid':p.pid}))
""".replace(
        "SECONDS", repr(str(a.seconds))
    ).replace(
        "EXTRA", repr(["--hdmi"] if a.hdmi else [])
    )
    print(remote(code))


if __name__ == "__main__":
    main()
