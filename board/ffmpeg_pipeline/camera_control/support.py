"""Small helpers for timestamps, files and read-only camera discovery."""

import datetime
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import json
from .config import ControlError


def stamp():
    return datetime.datetime.now().astimezone().isoformat()


def run_id():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def tail(path, lines=40):
    if not path or not Path(path).is_file():
        return []
    with open(path, "rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 16000))
        return handle.read().decode("utf-8", errors="replace").splitlines()[-lines:]


def camera_owners(device):
    if shutil.which("fuser"):
        args = ["fuser", device]
    elif shutil.which("lsof"):
        args = ["lsof", "-t", device]
    else:
        raise ControlError("Install lsof or fuser to verify camera ownership")
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise ControlError("Camera ownership check failed: " + result.stderr[-1000:])
    return sorted(set(result.stdout.split()))


def sensor_frame_rate(device):
    if device != "/dev/video44" or not shutil.which("v4l2-ctl"):
        return None
    result = subprocess.run(
        ["v4l2-ctl", "-d", "/dev/v4l-subdev2", "--get-subdev-fps"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    found = re.search(r"Frames per second:\s*([\d.]+)", result.stdout)
    return float(found[1]) if result.returncode == 0 and found else None
