"""Exercise the JSON socket boundary without starting media processes."""

import json
from pathlib import Path
import socket
import socketserver
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from camera_control.config import ControlError, ROOT
from camera_control.transport import Handler


class TransportTests(unittest.TestCase):
    def exchange(self, value, result=None, error=None):
        controller = Mock()
        controller.operation_lock = threading.RLock()
        controller.execute.side_effect = error
        controller.execute.return_value = result
        with tempfile.TemporaryDirectory() as folder:
            if hasattr(socketserver, "ThreadingUnixStreamServer"):
                endpoint = str(Path(folder) / "control.sock")
                server = socketserver.ThreadingUnixStreamServer(endpoint, Handler)
                family = socket.AF_UNIX
            else:
                # Windows verifies the same handler over loopback TCP only;
                # Linux-specific socket binding remains a board verification.
                server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
                endpoint = server.server_address
                family = socket.AF_INET
            server.controller = controller
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with socket.socket(family, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(endpoint)
                    client.sendall((json.dumps(value) + "\n").encode())
                    with client.makefile("rb") as output:
                        response = json.loads(output.readline())
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)
        return response, controller

    def test_query_preserves_response_shape(self):
        response, controller = self.exchange(
            {"action": "status", "payload": {}}, {"state": "running"}
        )
        self.assertEqual(response, {"ok": True, "result": {"state": "running"}})
        controller.execute.assert_called_once_with("status", {})

    def test_mutation_error_keeps_recovery_details(self):
        error = ControlError("failed", {"attempted": True, "restored": True})
        response, controller = self.exchange({"action": "start", "payload": {}}, error=error)
        self.assertFalse(response["ok"])
        self.assertTrue(response["result"]["recovery"]["restored"])
        controller.execute.assert_called_once()

    def test_non_object_request_never_reaches_controller(self):
        response, controller = self.exchange([])
        self.assertFalse(response["ok"])
        controller.execute.assert_not_called()

    def test_package_root_stays_outside_implementation_folder(self):
        self.assertEqual(ROOT, Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    unittest.main()
