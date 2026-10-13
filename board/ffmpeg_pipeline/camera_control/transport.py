"""Local Unix-socket server and CLI client; JSON is the stable wire format."""

import json
import os
import signal
import socket
import socketserver
import subprocess
import threading
import time
from .config import ROOT, ControlError
from .controller import Controller


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline(16385))
            if not isinstance(request, dict):
                raise ControlError("Request must be an object")
            action = request.get("action")
            if action in ("check", "status", "logs"):
                result = self.server.controller.execute(action, request.get("payload", {}))
            else:
                with self.server.controller.operation_lock:
                    result = self.server.controller.execute(action, request.get("payload", {}))
            response = {
                "ok": not (isinstance(result, dict) and "error" in result),
                "result": result,
            }
            if not response["ok"]:
                response["error"] = result["error"]
        except Exception as error:
            response = {"ok": False, "error": str(error)}
            if getattr(error, "recovery", None) is not None:
                response["result"] = {"recovery": error.recovery}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


def serve():
    # File locking is required by the Linux daemon, not by protocol unit tests.
    import fcntl

    state = ROOT / "state"
    state.mkdir(exist_ok=True)
    lockfile = open(state / "controller.lock", "w")
    fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    endpoint = state / "control.sock"
    if endpoint.exists():
        endpoint.unlink()
    controller = Controller()
    server = socketserver.ThreadingUnixStreamServer(str(endpoint), Handler)
    server.daemon_threads = True
    server.controller = controller
    os.chmod(endpoint, 0o600)
    threading.Thread(target=controller.monitor, daemon=True).start()

    def stop_signal(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_signal)
    signal.signal(signal.SIGTERM, stop_signal)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        controller.closed = True
        controller.stop()
        server.server_close()
        if endpoint.exists():
            endpoint.unlink()


def request(action, payload):
    endpoint = ROOT / "state/control.sock"
    if action in ("start", "preview-start"):
        result = subprocess.run(
            ["systemctl", "start", "evm-mediamtx.service", "evm-ffmpeg-control.service"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode:
            raise ControlError("Install services first: " + result.stderr.strip())
        deadline = time.monotonic() + 5
        while not endpoint.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
    if not endpoint.exists():
        if action == "check":
            return {"ok": True, "result": Controller().check()}
        if action in ("status", "stop", "record-stop", "preview-stop"):
            return {"ok": True, "result": {"state": "stopped", "recording": False}}
        raise ControlError("Controller is not running")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(75 if action in ("start", "stop") else 35)
        client.connect(str(endpoint))
        client.sendall((json.dumps({"action": action, "payload": payload}) + "\n").encode("utf-8"))
        with client.makefile("rb") as reader:
            return json.loads(reader.readline())
