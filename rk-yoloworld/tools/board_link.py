"""Local test helper: ADB transport only; never stores board credentials."""

import base64, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADB = Path(
    os.environ.get(
        "YOLOWORLD_ADB",
        str(ROOT.parents[1] / "Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe"),
    )
)


def remote(code, timeout=40):
    command = (
        "python3 -c 'import base64;exec(base64.b64decode(\""
        + base64.b64encode(code.encode()).decode()
        + "\"))'"
    )
    output = (
        subprocess.check_output([str(ADB), "shell", command], timeout=timeout)
        .decode(errors="replace")
        .replace("\r", "")
    )
    # This old vendor ADB sometimes returns 0 even when board Python failed.
    if any(line.startswith("Traceback (most recent call last):") for line in output.splitlines()):
        raise RuntimeError(
            "Board Python failed (ADB did not propagate its exit status):\n" + output[-6000:]
        )
    return output


def push(source, destination):
    subprocess.run(
        [str(ADB), "push", str(source), destination], check=True, stdout=subprocess.DEVNULL
    )
