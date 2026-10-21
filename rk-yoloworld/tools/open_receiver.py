import subprocess, json
from pathlib import Path

r = Path("rk-yoloworld/build")
log = (r / "receiver.log").open("w")
p = subprocess.Popen(
    [
        "ffplay",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-framedrop",
        "-sync",
        "ext",
        "-window_title",
        "YOLO-World - IMX415 detection test",
        "udp://0.0.0.0:1235?fifo_size=8192&overrun_nonfatal=1",
    ],
    stdout=log,
    stderr=log,
)
(r / "receiver.pid").write_text(str(p.pid))
print(json.dumps({"ffplayPid": p.pid}))
