"""Local real-board regression: two timed runs, then SIGINT + automatic restore.

Uses the explicitly scoped test wrapper; never terminates an unrelated process.
The third run also captures eight seconds of outgoing UDP for offline validation.
"""

import json
import subprocess
import sys
import time

from board_link import ROOT, remote


def run_tool(name, *args):
    subprocess.run([sys.executable, str(ROOT / "tools" / name), *args], check=True)


def snapshot():
    return json.loads(
        remote(
            """import json,sys
from pathlib import Path
sys.path.insert(0,'/userdata/av_dev/ffmpeg_pipeline')
from camera_control.transport import request
r=Path('/userdata/rk-yoloworld')
pid=int((r/'state/test-wrapper.pid').read_text())
try: active=b'run_with_restore.py' in Path('/proc',str(pid),'cmdline').read_bytes()
except OSError: active=False
logs=sorted((r/'logs').glob('*.jsonl'))
p=logs[-1] if logs else None
samples=p.read_text().splitlines() if p else []
print(json.dumps({'active':active,'log':p.name if p else None,'samples':len(samples),
 'errors':p.with_suffix('.log').read_text() if p else '',
 'wrapper':(r/'state/test-wrapper.log').read_text(),
 'status':request('status',{})}))
"""
        )
    )


def main():
    rows = []
    for index, seconds in enumerate((5, 5, 30), 1):
        previous_log = snapshot()["log"]
        run_tool("start_board_test.py", "--seconds", str(seconds))
        deadline = time.monotonic() + 120
        interrupted = False
        while True:
            data = snapshot()
            if (
                index == 3
                and data["active"]
                and data["log"] != previous_log
                and data["samples"] >= 2
                and not interrupted
            ):
                run_tool("sniff_sample.py")
                run_tool("stop_board_test.py")
                interrupted = True
            if not data["active"]:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Wrapper did not finish; inspect before further action")
            time.sleep(1)
        status = data["status"]
        assert status.get("ok"), status
        actual = status["result"]
        assert actual["state"] == "running" and actual["previewRunning"], actual
        assert actual["config"]["codec"] == "h265", actual["config"]
        assert actual["config"]["width"] == 3840 and actual["config"]["fps"] == 60
        assert "Original video state restored." in data["wrapper"], data["wrapper"]
        errors = data["errors"]
        assert "encoder_exit_status=0" in errors, errors
        for text in ("Non-monotonous", "non monotonically", "Invalid buffer", "fatal:"):
            assert text not in errors, errors
        rows.append(
            {
                "run": index,
                "log": data["log"],
                "samples": data["samples"],
                "sigint": interrupted,
                "restored": True,
                "encoderExit": 0,
            }
        )
        print(json.dumps(rows[-1]), flush=True)
    (ROOT / "build/lifecycle-results.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
