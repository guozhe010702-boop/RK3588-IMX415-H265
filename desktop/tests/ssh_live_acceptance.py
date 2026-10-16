"""Ten real GUI SSH/RTSP connect-close cycles. Temporary key is always removed."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import threading
import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'desktop'))
from PySide6.QtWidgets import QApplication
from evm_console.window import MainWindow
from evm_console.ssh import trust_host, connect_ssh, invoke
from evm_console.core import Connection, executable
from evm_console.files import remote_digest, copy_remote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--provision-temporary-key', action='store_true', required=True)
    parser.add_argument('--cycles', type=int, default=10)
    parser.add_argument('--media', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ['EVM_CONSOLE_DATA'] = str((args.output / 'user-data').resolve())
    adb = str(ROOT.parent / 'Tools/platform-tools/adb.exe')
    def run(*arguments):
        return subprocess.check_output([adb, *arguments], text=True, timeout=15)
    key = paramiko.RSAKey.generate(2048)
    private = args.output / 'temporary-key'
    key.write_private_key_file(str(private))
    tag = 'av-dev-acceptance-' + uuid.uuid4().hex
    public = args.output / 'temporary-key.pub'
    public.write_text(key.get_name() + ' ' + key.get_base64() + ' ' + tag + '\n')
    remote_public = '/tmp/' + tag + '.pub'
    remote_helper = '/tmp/' + tag + '.py'
    run('push', str(public), remote_public)
    run('push', str(ROOT / 'tools/tests/temporary_ssh_key.py'), remote_helper)
    app = QApplication([])
    results = []
    media = {}
    window = None
    try:
        run('shell', 'python3 ' + remote_helper + ' add ' + remote_public)
        host_key = run('shell', 'cat /etc/ssh/ssh_host_ed25519_key.pub').split()
        trust_host({'host': '192.168.2.221', 'type': host_key[0], 'key': host_key[1]})
        for index in range(args.cycles):
            window = MainWindow()
            window.setWindowTitle('真实 SSH / RTSP 连接回归 ' + str(index+1) + '/10')
            window.host.setText('192.168.2.221')
            window.auth.setCurrentIndex(1)
            window.key_file.setText(str(private.resolve()))
            window.show()
            started = time.monotonic()
            window.connect_board()
            deadline = started + 15
            while window.canvas.painted_frames == 0 and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            connected_time = time.monotonic() - started
            entry = {'cycle': index+1, 'sshConnected': window.ssh_connected,
                     'newFramesPainted': window.canvas.painted_frames,
                     'connectToFirstPaintSeconds': connected_time,
                     'decoderFirstFrameSeconds': window.video.first_frame_seconds}
            results.append(entry)
            if not window.ssh_connected or not window.canvas.painted_frames:
                raise RuntimeError('Connection failed: ' + str(entry))
            window.close()
            deadline = time.monotonic() + 12
            while window.isVisible() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            if any(w.isRunning() for w in (window.ssh, window.video, window.files, window.performance)):
                raise RuntimeError('Worker remained after close')
            window = None
        if args.media:
            client = connect_ssh(Connection(auth='key', key_file=str(private.resolve())), '')
            recording = False
            try:
                started = invoke(client, 'record-start')
                if not started['ok']:
                    raise RuntimeError(str(started))
                recording = True
                time.sleep(10)
                snapshot = invoke(client, 'snapshot')
                stopped = invoke(client, 'record-stop')
                recording = False
                if not snapshot['ok'] or not stopped['ok']:
                    raise RuntimeError(str((snapshot, stopped)))
                movie = stopped['result']['lastRecording']['file']
                jpeg = snapshot['result']['file']
                media['recording'] = stopped['result']['lastRecording']['probe']
                with client.open_sftp() as sftp:
                    for name, remote in [('movie', movie), ('snapshot', jpeg)]:
                        digest = remote_digest(client, remote)
                        local = copy_remote(sftp, remote, args.output / '下载验证', threading.Event(), lambda *_: None, digest)
                        media[name] = {'bytes': Path(local).stat().st_size, 'sha256': digest}
                        if name == 'movie':
                            playback = subprocess.run([executable('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                                '-i', local, '-f', 'null', '-'], capture_output=True, timeout=30)
                            media['downloadedMp4DecodeExitCode'] = playback.returncode
                media['liveStillRunning'] = invoke(client, 'status')['result']['state'] == 'running'
            finally:
                if recording:
                    invoke(client, 'record-stop')
                client.close()
    finally:
        if window:
            window.close()
            deadline = time.monotonic() + 12
            while window.isVisible() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
        cleanup = run('shell', 'python3 ' + remote_helper + ' remove ' + remote_public)
        run('shell', 'rm -f ' + remote_helper + ' ' + remote_public)
        private.unlink(missing_ok=True)
        report = {'scope': 'actual-SSH-RTSP-GUI-connect-close', 'cycles': results,
                  'temporaryKeyRemoved': json.loads(cleanup)['removed'], 'media': media}
        (args.output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
