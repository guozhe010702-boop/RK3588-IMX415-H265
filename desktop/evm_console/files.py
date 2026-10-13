import os
import hashlib
import json
import re
import shlex
import time
from pathlib import Path, PurePosixPath
import queue
import stat
import threading
from PySide6.QtCore import QThread, Signal
from .core import REMOTE_ROOT
from .ssh import connect_ssh


def checked_remote(sftp, path):
    pure = PurePosixPath(path)
    if pure.parent.as_posix() not in (REMOTE_ROOT + "/recordings", REMOTE_ROOT + "/snapshots"):
        raise ValueError("文件必须位于板端录像或截图目录")
    if pure.suffix.lower() not in (".mp4", ".jpg") or pure.name.endswith(".partial.mp4"):
        raise ValueError("只下载已完成的 MP4 或 JPEG")
    actual = sftp.normalize(str(pure))
    if actual != str(pure):
        raise ValueError("拒绝下载目录外的链接文件")
    info = sftp.lstat(actual)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("下载对象不是普通文件")
    return actual, info


HASH_SCRIPT = """import hashlib,json,pathlib,sys
p=pathlib.Path(json.load(sys.stdin)['path'])
root=pathlib.Path('/userdata/av_dev/ffmpeg_pipeline')
assert p.parent in (root/'recordings',root/'snapshots') and p.suffix in ('.jpg','.mp4')
assert not p.name.endswith('.partial.mp4') and p.resolve()==p and p.is_file()
before=p.stat(); h=hashlib.sha256()
with p.open('rb') as f:
 while True:
  b=f.read(1048576)
  if not b: break
  h.update(b)
after=p.stat()
assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
print(h.hexdigest())
"""


def remote_digest(client, path):
    # Only this fixed script is executed. The requested path travels via stdin.
    streams = client.exec_command("python3 -c " + shlex.quote(HASH_SCRIPT), timeout=30)
    stdin, stdout, stderr = streams
    try:
        stdin.write(json.dumps({"path": path}) + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        digest = stdout.read(256).decode("ascii").strip()
        if not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("无法校验板端文件 SHA-256，请刷新文件列表后重试")
        return digest
    finally:
        for stream in streams:
            stream.close()
        stdout.channel.close()


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_remote(sftp, remote, directory, cancel, progress, expected_digest=None):
    remote, info = checked_remote(sftp, remote)
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    name = PurePosixPath(remote).name
    if (
        re.search(r'[<>:"\\|?*\x00-\x1f]', name)
        or name.endswith((" ", "."))
        or name.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("板端文件名不能直接保存到 Windows，请重命名后下载")
    final = folder / PurePosixPath(remote).name
    if final.exists():
        if (
            expected_digest
            and final.stat().st_size == info.st_size
            and file_digest(final) == expected_digest
        ):
            return str(final)
        raise ValueError("本地已有同名文件且内容尚未验证或不同，请更换下载目录")
    partial = final.with_name(final.name + ".part")
    done = 0
    digest = hashlib.sha256()
    try:
        with sftp.open(remote, "rb") as source, partial.open("wb") as output:
            source.prefetch(info.st_size, max_concurrent_requests=16)
            while True:
                if cancel.is_set():
                    raise InterruptedError("下载已取消，临时文件已清理")
                chunk = source.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, info.st_size)
            output.flush()
            os.fsync(output.fileno())
        if done != info.st_size or sftp.stat(remote).st_size != info.st_size:
            raise ValueError("文件长度发生变化或下载不完整，请重新下载")
        if expected_digest and digest.hexdigest() != expected_digest:
            raise ValueError("文件 SHA-256 校验失败，临时文件已清理")
        if file_digest(partial) != digest.hexdigest():
            raise ValueError("本地文件写入校验失败，临时文件已清理")
        partial.replace(final)
        return str(final)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


class FileWorker(QThread):
    listing = Signal(list)
    progress = Signal(str, object, object)
    completed = Signal(str, str)
    failure = Signal(str)
    busy = Signal(bool)

    def __init__(self):
        super().__init__()
        self.jobs = queue.Queue()
        self.stop_event = threading.Event()
        self.cancel = threading.Event()
        self.connection = None
        self.password = ""
        self.client = None
        self.generation = 0
        self.lock = threading.Lock()

    def configure(self, connection, password):
        with self.lock:
            if self.connection != connection or self.password != password:
                self.generation += 1
                self.cancel.set()
            self.connection = connection
            self.password = password

    def disconnect(self):
        self.configure(None, "")
        if self.client:
            self.client.close()

    def submit(self, action, payload=None):
        with self.lock:
            self.jobs.put((self.generation, action, payload, self.connection, self.password))

    def shutdown(self):
        self.stop_event.set()
        self.cancel.set()
        if self.client:
            self.client.close()

    def run(self):
        while not self.stop_event.is_set():
            try:
                generation, action, payload, connection, password = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            with self.lock:
                if generation != self.generation:
                    continue
                self.cancel.clear()
            self.busy.emit(True)
            sftp = None
            try:
                if not connection:
                    raise ValueError("请先连接开发板")
                self.client = connect_ssh(connection, password)
                sftp = self.client.open_sftp()
                sftp.get_channel().settimeout(10)
                if generation != self.generation or self.stop_event.is_set():
                    continue
                if action == "list":
                    rows = []
                    for folder in ("recordings", "snapshots"):
                        for info in sftp.listdir_attr(REMOTE_ROOT + "/" + folder):
                            if stat.S_ISREG(info.st_mode) and info.filename.endswith(
                                (".mp4", ".jpg")
                            ):
                                rows.append(
                                    {
                                        "path": REMOTE_ROOT + "/" + folder + "/" + info.filename,
                                        "name": info.filename,
                                        "bytes": info.st_size,
                                        "modified": info.st_mtime,
                                        "complete": not info.filename.endswith(".partial.mp4"),
                                    }
                                )
                    if generation == self.generation:
                        self.listing.emit(
                            sorted(rows, key=lambda row: row["modified"], reverse=True)
                        )
                elif action == "download":
                    remote, folder = payload
                    remote, _ = checked_remote(sftp, remote)
                    digest = remote_digest(self.client, remote)
                    last_progress = [0]

                    def progress(done, total):
                        now = time.monotonic()
                        if generation == self.generation and (
                            done == total or now - last_progress[0] >= 0.1
                        ):
                            last_progress[0] = now
                            self.progress.emit(remote, done, total)

                    local = copy_remote(sftp, remote, folder, self.cancel, progress, digest)
                    if generation == self.generation:
                        self.completed.emit(remote, local)
            except Exception as error:
                if generation == self.generation and not self.stop_event.is_set():
                    self.failure.emit(str(error))
            finally:
                for resource in (sftp, self.client):
                    try:
                        if resource:
                            resource.close()
                    except Exception:
                        # A lost transport may also fail while closing its SFTP channel.
                        pass
                self.client = None
                self.busy.emit(False)
        self.password = ""
