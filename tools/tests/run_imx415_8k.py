"""Run the real-camera lab via ADB; keep movies/results local and restore prior live state."""

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import time

from run_8k_lab import ADB, DEST, ROOT, push, remote


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
    p.add_argument("--display-scale", action="store_true")
    a = p.parse_args()
    if not 120 <= a.frames <= 3600:
        p.error("frames must be 120..3600")
    if a.preview and (not a.rtsp or a.mode != "encode30"):
        p.error("--preview requires --rtsp --mode encode30")
    if a.mode == "decode60" and (not a.input or not a.manifest):
        p.error("decode60 requires --input and --manifest from prepare_camera_8k60.py")
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
    for flag in ("handover", "rtsp", "display_scale"):
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
    player = None
    try:
        if a.preview:
            ffplay = shutil.which("ffplay")
            if not ffplay:
                raise RuntimeError("ffplay not on PC PATH")
            time.sleep(2)
            player = subprocess.Popen(
                [
                    ffplay,
                    "-window_title",
                    "IMX415 real 4K to 8K30 / spatial upscale",
                    "-rtsp_transport",
                    "tcp",
                    "-framedrop",
                    "-vf",
                    "scale=1280:-2",
                    "rtsp://" + a.board_ip + ":8555/imx415-upscaled-8k30",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        deadline = time.monotonic() + 200
        while time.monotonic() < deadline:
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
        # Only our exact board worker can be signalled. Its finally restores the pipeline.
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
    return 0 if result.get("shortTestPassed") and result.get("restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
