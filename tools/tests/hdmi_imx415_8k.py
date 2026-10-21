"""Manage the board-only 8K VPU -> RGA -> HDMI reader without restarting capture."""

import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time

from run_8k_lab import ADB, DEST, ROOT, push, remote

STATE = DEST + "/state/hdmi-8k-active.json"


def status():
    return json.loads(
        remote(
            "import json,time;from pathlib import Path;p=Path(" + repr(STATE) + ");"
            "a=json.loads(p.read_text()) if p.exists() else {};d=Path(a.get('output','/nonexistent'));"
            "s=d/'status.json';w=Path('/proc/{}/cmdline'.format(a.get('pid',0)));"
            "c=w.read_bytes() if w.exists() else b'';"
            "alive=b'hdmi_8k.py' in c and str(d).encode() in c;"
            "age=time.time()-s.stat().st_mtime if s.exists() else None;"
            "print(json.dumps(dict(active=alive,stale=not alive or age is None or age>3,"
            "ageSeconds=age,worker=a,metrics=json.loads(s.read_text()) if s.exists() else None)))"
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("start", "status", "stop", "collect"))
    a = p.parse_args()
    current = status()
    if a.action == "start" and not current["active"]:
        tag = "hdmi-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = DEST + "/lab8k-camera/" + tag
        remote(
            "from pathlib import Path;r=Path(" + repr(DEST) + ");d=Path(" + repr(dest) + ");"
            "d.mkdir(parents=True);(r/'state').mkdir(exist_ok=True);"
            "(d/'decoder-before.py').write_bytes((r/'camera_control/decoder.py').read_bytes())"
        )
        for name in ("camera_control/decoder.py", "tests/hdmi_8k.py"):
            push(ROOT / "board/ffmpeg_pipeline" / name, DEST + "/" + name)
        args = ["python3", DEST + "/tests/hdmi_8k.py", "--output", dest + "/evidence"]
        remote(
            "import subprocess,json;from pathlib import Path;d=Path(" + repr(dest) + ");"
            "f=(d/'runner.log').open('w');p=subprocess.Popen("
            + repr(args)
            + ",stdin=subprocess.DEVNULL,"
            "stdout=f,stderr=f,start_new_session=True);state=Path(" + repr(STATE) + ");"
            "t=state.with_suffix('.tmp');t.write_text(json.dumps(dict(pid=p.pid,output=str(d/'evidence'),tag=d.name)));t.replace(state)"
        )
        for _ in range(12):
            time.sleep(1)
            current = status()
            if not current["active"]:
                raise RuntimeError(
                    remote(
                        "from pathlib import Path;print(Path("
                        + repr(dest + "/runner.log")
                        + ").read_text()[-6000:])"
                    )
                )
            if (current.get("metrics") or {}).get("display", {}).get("frame", 0) > 0:
                break
        else:
            raise RuntimeError(
                "HDMI reader started but no decoded frames yet; inspect its output directory"
            )
    elif a.action == "stop" and current["active"]:
        output = current["worker"]["output"]
        remote(
            "from pathlib import Path;d=Path("
            + repr(output)
            + ").resolve();r=Path("
            + repr(DEST + "/lab8k-camera")
            + ").resolve();"
            "assert r in d.parents;(d/'stop.request').touch()"
        )
        for _ in range(15):
            time.sleep(1)
            current = status()
            if not current["active"]:
                break
        else:
            raise RuntimeError("HDMI worker is still stopping; encoder has not been touched")
    if a.action == "collect":
        if not current.get("worker"):
            raise RuntimeError("No HDMI test has been registered")
        output = current["worker"]["output"]
        folder = ROOT / ".cache/hdmi-8k" / Path(output).parent.name
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(ADB), "pull", str(Path(output).parent).replace("\\", "/"), str(folder)], check=True
        )
        print("Saved board logs and CSV to", folder, flush=True)
    print(json.dumps(current, indent=2), flush=True)


if __name__ == "__main__":
    main()
