from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import re
import shutil
import sys

REMOTE_ROOT = "/userdata/av_dev/ffmpeg_pipeline"
ACTIONS = {
    "check",
    "status",
    "start",
    "stop",
    "preview-start",
    "preview-stop",
    "decode-start",
    "decode-stop",
    "record-start",
    "record-stop",
    "snapshot",
    "logs",
}
DEFAULT_CONFIG = {
    "device": "/dev/video44",
    "codec": "h265",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "bitrate": 2500000,
    "gop": 30,
}


def data_root():
    path = Path(
        os.environ.get(
            "EVM_CONSOLE_DATA",
            str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EVM3588CameraConsole"),
        )
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Connection:
    host: str = "192.168.2.221"
    port: int = 22
    username: str = "root"
    auth: str = "password"
    key_file: str = ""
    remember: bool = False

    def validate(self):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", self.host) or not 1 <= self.port <= 65535:
            raise ValueError("请填写有效的板子地址和 SSH 端口")
        if not self.username.strip():
            raise ValueError("请填写 SSH 用户名")
        if self.auth == "key" and not Path(self.key_file).is_file():
            raise ValueError("请选择存在的 SSH 私钥文件")
        return self

    @property
    def credential_id(self):
        return f"{self.username}@{self.host}:{self.port}"

    @property
    def rtsp_url(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"rtsp://{host}:8554/imx415"


def load_preferences():
    try:
        value = json.loads((data_root() / "preferences.json").read_text(encoding="utf-8"))
        allowed = set(asdict(Connection()))
        connection = Connection(
            **{k: v for k, v in value.get("connection", {}).items() if k in allowed}
        )
        return (
            connection,
            value.get("download_dir", str(Path.home() / "Videos" / "EVM3588")),
            bool(value.get("auto_download", False)),
        )
    except (OSError, ValueError, TypeError):
        return Connection(), str(Path.home() / "Videos" / "EVM3588"), False


def save_preferences(connection, download_dir, auto_download):
    value = {
        "connection": asdict(connection),
        "download_dir": str(download_dir),
        "auto_download": bool(auto_download),
    }
    # Retain display preferences when updating connection/media settings.
    value["preview_quality"] = load_preview_quality()
    temp = data_root() / "preferences.tmp"
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(data_root() / "preferences.json")


PREVIEW_PRESETS = {"流畅": (640, 15), "均衡": (960, 30), "清晰": (1280, 30), "性能 60 fps": (1280, 60)}
PERFORMANCE_CONFIG = dict(DEFAULT_CONFIG, width=3840, height=2160, fps=60, bitrate=20000000, gop=60)


def load_preview_quality():
    try:
        value = json.loads((data_root() / "preferences.json").read_text(encoding="utf-8")).get(
            "preview_quality", "清晰"
        )
        return value if value in PREVIEW_PRESETS else "清晰"
    except (OSError, ValueError, TypeError):
        return "清晰"


def save_preview_quality(quality):
    if quality not in PREVIEW_PRESETS:
        raise ValueError("Unknown preview quality")
    path = data_root() / "preferences.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    value["preview_quality"] = quality
    temp = data_root() / "preferences.tmp"
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def executable(name):
    roots = [
        Path(sys.executable).parent,
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])),
    ]
    for root in roots:
        for folder in ("ffmpeg", "vendor/ffmpeg", ""):
            candidate = root / folder / (name + ".exe" if os.name == "nt" else name)
            if candidate.is_file():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"未找到 {name}；请使用包含 ffmpeg 目录的完整便携包")


def parse_response(text):
    value = json.loads(text)
    if not isinstance(value, dict) or type(value.get("ok")) is not bool:
        raise ValueError("板端返回的控制结果格式不正确")
    if value["ok"] and not isinstance(value.get("result"), dict):
        raise ValueError("板端结果缺少对象字段 result")
    return value


def controls(status, connected, busy):
    running = status.get("state") == "running"
    recording = bool(status.get("recording"))
    enabled = connected and not busy
    return {
        "start": enabled and not running,
        "stop": enabled and status.get("state") not in ("stopped", None),
        "snapshot": enabled and running,
        "record-start": enabled and running and not recording,
        "record-stop": enabled and recording,
        "apply": enabled and not recording,
        "hdmi": enabled and running,
    }


def explain_error(message):
    text = str(message)
    mapping = {
        "Authentication failed": "SSH 认证失败，请检查用户名、密码或密钥",
        "Camera busy": "摄像头被其他程序占用",
        "Stop and finalize recording": "请先停止录像并等待 MP4 封口，再修改参数",
        "Required hardware encoder": "板端缺少所需硬件编码器",
        "Less than 1 GiB": "板端剩余空间不足 1 GiB，不能开始录像",
        "Stream is not ready": "直播尚未就绪，请等待出帧",
        "Connection refused": "连接被拒绝，请检查板子地址与服务",
        "Controller service is not running": "板端控制服务未运行；SSH 已连接，可点击启动直播",
        "timed out": "连接或操作超时，请检查网络并查询状态",
        "Driver selected": "驱动没有采用请求的分辨率，已尝试恢复原直播",
        "different capture size": "驱动没有采用请求的分辨率，已尝试恢复原直播",
    }
    mapping["Requested fps exceeds"] = "请求帧率超过当前传感器帧率，请降低编码帧率"
    return next((cn for key, cn in mapping.items() if key in text), text)


class FrameAssembler:
    def __init__(self, size):
        self.size = size
        self.buffer = bytearray()
        self.complete_frames = 0
        self.discarded_frames = 0

    def feed(self, chunk):
        self.buffer.extend(chunk)
        latest = None
        count = len(self.buffer) // self.size
        if count:
            self.complete_frames += count
            self.discarded_frames += count - 1
            offset = (count - 1) * self.size
            latest = bytes(self.buffer[offset : offset + self.size])
            del self.buffer[: count * self.size]
        return latest
