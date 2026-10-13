"""Default configuration, constants and validation; no device side effects."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "device": "/dev/video44",
    "codec": "h265",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "bitrate": 2500000,
    "gop": 30,
}
URL = "rtsp://127.0.0.1:8554/imx415"
MIN_FREE = 1024**3
ACTIONS = (
    "check",
    "start",
    "stop",
    "status",
    "record-start",
    "record-stop",
    "preview-start",
    "preview-stop",
    "snapshot",
    "logs",
)


class ControlError(Exception):
    def __init__(self, message, recovery=None):
        super().__init__(message)
        self.recovery = recovery


def validate_config(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ControlError("Configuration must be an object with known fields")
    result = dict(DEFAULTS, **value)
    if not isinstance(result["device"], str) or not re.fullmatch(
        r"/dev/video[0-9]+", result["device"]
    ):
        raise ControlError("Invalid V4L2 device")
    if result["codec"] not in ("h265", "h264"):
        raise ControlError("codec must be h265 or h264")
    for key, low, high in [
        ("width", 96, 8192),
        ("height", 64, 8192),
        ("fps", 1, 60),
        ("bitrate", 100000, 20000000),
        ("gop", 1, 600),
    ]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ControlError("Invalid {} (range {}..{})".format(key, low, high))
    if result["width"] % 2 or result["height"] % 2:
        raise ControlError("NV12 width and height must be even")
    return result
