import subprocess
from pathlib import Path

r = Path("rk-yoloworld/build")
pid = int((r / "receiver.pid").read_text())
# Only the receiver created by this test, verified by its PID and command line.
check = subprocess.run(
    [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | Select-Object -ExpandProperty CommandLine",
    ],
    capture_output=True,
    text=True,
)
if "YOLO-World - IMX415 detection test" in check.stdout:
    subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)
