"""Run the real-camera lab via ADB; keep movies/results local and restore prior live state."""

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time

from run_8k_lab import ADB, DEST, ROOT, push, remote


def preview_command(ffplay, url, backend="software"):
    command = [
        ffplay,
        "-window_title",
        "IMX415 REAL CAMERA - 4K to 8K30",
        "-loglevel",
        "info",
        "-threads",
        "8",
        "-an",
        "-framedrop",
        "-noinfbuf",
        "-x",
        "1280",
        "-y",
        "720",
    ]
    if backend == "intel-qsv":
        return command + ["-f", "nut", "-probesize", "32768", "-analyzeduration", "0", "pipe:0"]
    return command + ["-rtsp_transport", "tcp", "-vf", "scale=1280:-2:flags=fast_bilinear", url]


def qsv_decode_command(ffmpeg, url, progress):
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "info",
        "-stats_period",
        "1",
        "-progress",
        str(progress),
        "-init_hw_device",
        "qsv=hw:hw,child_device_type=d3d11va",
        "-filter_hw_device",
        "hw",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
        "-thread_queue_size",
        "4",
        "-hwaccel",
        "qsv",
        "-hwaccel_output_format",
        "qsv",
        "-c:v",
        "hevc_qsv",
        "-async_depth",
        "2",
        "-i",
        url,
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "vpp_qsv=w=1280:h=720:format=nv12,hwdownload,format=nv12",
        "-c:v",
        "rawvideo",
        "-fps_mode",
        "passthrough",
        "-flush_packets",
        "1",
        "-f",
        "nut",
        "pipe:1",
    ]


def wait_preview_stream(ffprobe, url, output):
    command = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "3000000",
        "-analyzeduration",
        "1000000",
        "-probesize",
        "1048576",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate",
        "-of",
        "json",
        url,
    ]
    with (output / "preview-probe.log").open("w", encoding="utf-8") as log:
        for _ in range(3):
            try:
                reply = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=6,
                )
                log.write(reply.stdout + reply.stderr + "\n")
                log.flush()
                streams = json.loads(reply.stdout or "{}").get("streams", [])
                if reply.returncode == 0 and streams:
                    stream = streams[0]
                    if (
                        stream.get("codec_name"),
                        stream.get("width"),
                        stream.get("height"),
                        stream.get("r_frame_rate"),
                    ) != ("hevc", 7680, 4320, "30/1"):
                        raise RuntimeError("Unexpected preview format: " + json.dumps(stream))
                    (output / "preview-stream.json").write_text(json.dumps(stream, indent=2))
                    return stream
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                log.write(str(error) + "\n")
            time.sleep(0.5)
    raise RuntimeError("PC cannot read camera RTSP; see " + str(output / "preview-probe.log"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("encode30", "capture60", "decode60"), required=True)
    p.add_argument("--frames", type=int, default=600)
    p.add_argument("--input", type=Path)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--handover", action="store_true")
    p.add_argument("--rtsp", action="store_true")
    p.add_argument("--preview", action="store_true", help="PC ffplay on real camera RTSP")
    p.add_argument("--board-ip", default="192.168.2.221")
    p.add_argument(
        "--preview-backend",
        choices=("software", "intel-qsv"),
        default="software",
        help="intel-qsv: full 8K GPU decode and GPU downscale, then ffplay",
    )
    p.add_argument("--display-scale", action="store_true")
    p.add_argument(
        "--live", action="store_true", help="continuous preview until window closes; no MP4"
    )
    a = p.parse_args()
    if not 120 <= a.frames <= 3600:
        p.error("frames must be 120..3600")
    if a.preview and (not a.rtsp or a.mode != "encode30"):
        p.error("--preview requires --rtsp --mode encode30")
    if a.mode == "decode60" and (not a.input or not a.manifest):
        p.error("decode60 requires --input and --manifest from prepare_camera_8k60.py")
    if a.live and (a.mode != "encode30" or not a.rtsp or not a.preview):
        p.error("--live requires --mode encode30 --rtsp --preview")
    tag = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + a.mode
    dest = DEST + "/lab8k-camera/" + tag
    output = ROOT / ".cache/imx415-8k" / tag
    output.mkdir(parents=True)
    remote("from pathlib import Path;Path(" + repr(dest) + ").mkdir(parents=True)")
    remote(
        "from pathlib import Path;r=Path("
        + repr(DEST)
        + ");[(r/p).mkdir(parents=True,exist_ok=True) for p in ('tests','profiles/8k')]"
    )
    for name in ("codec_metrics.py", "imx415_8k.py"):
        push(ROOT / "board/ffmpeg_pipeline/tests" / name, DEST + "/tests/" + name)
    push(
        ROOT / "board/ffmpeg_pipeline/profiles/8k/mediamtx.yml", DEST + "/profiles/8k/mediamtx.yml"
    )
    args = [
        "python3",
        DEST + "/tests/imx415_8k.py",
        "--mode",
        a.mode,
        "--frames",
        str(a.frames),
        "--output",
        dest + "/evidence",
    ]
    for flag in ("handover", "rtsp", "display_scale", "live"):
        if getattr(a, flag):
            args.append("--" + flag.replace("_", "-"))
    if a.mode == "decode60":
        for local, name in ((a.input, "camera-8k60.mp4"), (a.manifest, "camera-source.json")):
            push(local, dest + "/" + name)
        args += ["--input", dest + "/camera-8k60.mp4", "--manifest", dest + "/camera-source.json"]
    code = "import subprocess,json;from pathlib import Path;d=Path(" + repr(dest) + ");"
    code += (
        "f=(d/'runner.log').open('w');p=subprocess.Popen("
        + repr(args)
        + ",stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True);print(p.pid)"
    )
    pid = int(remote(code).strip())
    print("Board started PID", pid, "; evidence:", output, flush=True)
    player = player_log = decoder = decoder_log = None
    result = None
    preview_stream = None
    try:
        if a.preview:
            ffplay = shutil.which("ffplay")
            ffprobe = shutil.which("ffprobe")
            if not ffplay or not ffprobe:
                raise RuntimeError("ffplay and ffprobe must be on PC PATH")
            url = "rtsp://" + a.board_ip + ":8555/imx415-upscaled-8k30"
            preview_stream = wait_preview_stream(ffprobe, url, output)
            command = preview_command(ffplay, url, a.preview_backend)
            (output / "ffplay-command.json").write_text(json.dumps(command, indent=2))
            player_log = (output / "ffplay.log").open("wb")
            if a.preview_backend == "intel-qsv":
                ffmpeg = shutil.which("ffmpeg")
                if not ffmpeg:
                    raise RuntimeError("Intel QSV preview requires PC FFmpeg with hevc_qsv/vpp_qsv")
                decoder_command = qsv_decode_command(ffmpeg, url, output / "preview-progress.txt")
                (output / "preview-decoder-command.json").write_text(
                    json.dumps(decoder_command, indent=2)
                )
                decoder_log = (output / "preview-decoder.log").open("wb")
                decoder = subprocess.Popen(
                    decoder_command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=decoder_log,
                )
            player = subprocess.Popen(
                command,
                stdin=decoder.stdout if decoder is not None else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=player_log,
            )
            if decoder is not None:
                decoder.stdout.close()
            (output / "player.json").write_text(
                json.dumps(
                    {
                        "pid": player.pid,
                        "url": url,
                        "live": a.live,
                        "backend": a.preview_backend,
                        "decoderPid": decoder.pid if decoder is not None else None,
                        "log": str(output / "ffplay.log"),
                    },
                    indent=2,
                )
            )
            print(
                "Preview PID",
                player.pid,
                "; close its window to stop. Log:",
                output / "ffplay.log",
                flush=True,
            )
        deadline = time.monotonic() + 200
        while a.live or time.monotonic() < deadline:
            if player is not None and player.poll() is not None:
                if player.returncode != 0:
                    raise RuntimeError(
                        "ffplay exited with code {}. See {}".format(
                            player.returncode, output / "ffplay.log"
                        )
                    )
                print(
                    "Preview window closed; stopping this camera lab and restoring prior state.",
                    flush=True,
                )
                break
            if decoder is not None and decoder.poll() is not None:
                raise RuntimeError(
                    "Intel QSV decoder exited with code {}. See {}".format(
                        decoder.returncode, output / "preview-decoder.log"
                    )
                )
            reply = remote(
                "from pathlib import Path;import json;p=Path("
                + repr(dest + "/evidence/result.json")
                + ");s=Path('/proc/"
                + str(pid)
                + "/stat');print(p.read_text() if p.exists() else json.dumps({'waiting':s.exists() and s.read_text().split()[2]!='Z'}))"
            )
            result = json.loads(reply)
            if "waiting" not in result:
                break
            if not result["waiting"]:
                raise RuntimeError(
                    remote(
                        "from pathlib import Path;print(Path("
                        + repr(dest + "/runner.log")
                        + ").read_text()[-6000:])"
                    )
                )
            time.sleep(2)
        else:
            raise TimeoutError("Board lab exceeded 200 seconds")
    finally:
        if player is not None and player.poll() is None:
            player.terminate()
            player.wait(timeout=8)
        if player_log is not None:
            player_log.close()
        if decoder is not None:
            try:
                decoder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                decoder.terminate()
                decoder.wait(timeout=5)
            if decoder.stdout is not None:
                decoder.stdout.close()
        if decoder_log is not None:
            decoder_log.close()
        # Only our exact board worker can be signalled. Its finally restores the pipeline.
        if a.live:
            remote(
                "from pathlib import Path;p=Path("
                + repr(dest + "/evidence/stop.request")
                + ");p.parent.mkdir(parents=True,exist_ok=True);p.touch()"
            )
        else:
            remote(
                "import os,signal;from pathlib import Path;p=Path('/proc/"
                + str(pid)
                + "/cmdline');c=p.read_bytes() if p.exists() else b'';os.kill("
                + str(pid)
                + ",signal.SIGINT) if b'imx415_8k.py' in c else None"
            )
        # Allow MP4 finalization and original live/HDMI restoration before pulling.
        for _ in range(15):
            alive = remote(
                "from pathlib import Path;p=Path('/proc/"
                + str(pid)
                + "/stat');print(p.exists() and p.read_text().split()[2]!='Z')"
            ).strip()
            if alive != "True":
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "Board worker still restoring; inspect its runner.log before another test"
            )
        subprocess.run([str(ADB), "pull", dest, str(output)], check=True, stdout=subprocess.DEVNULL)
    if result is None or "waiting" in result:
        result = json.loads(
            remote(
                "from pathlib import Path;print(Path("
                + repr(dest + "/evidence/result.json")
                + ").read_text())"
            )
        )
    result["pcPreview"] = {
        "backend": a.preview_backend,
        "stream": preview_stream,
        "log": str(output / "ffplay.log"),
        "exitCode": player.returncode if player is not None else None,
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in ("sensor", "captureSamples", "provenance")
            },
            indent=2,
        ),
        flush=True,
    )
    return (
        0
        if (result.get("shortTestPassed") or result.get("livePreviewEnded"))
        and result.get("restored")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
