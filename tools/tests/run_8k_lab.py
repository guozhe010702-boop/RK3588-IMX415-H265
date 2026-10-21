"""PC ADB staging/runner for the av_dev 8K codec lab, not a camera preset.

Uploads only labelled fixtures and the isolated test script; saves results in
.cache and leaves boot/system libraries untouched. Stops capture only when
--handover is explicitly provided; each board case restores its saved state.
"""

import argparse
import base64
import datetime
import json
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ADB = ROOT.parent / "Tools/RKDevTool_296/unpacked/RKDevTool_Release_v2.96/bin/adb.exe"
DEST = "/userdata/av_dev/ffmpeg_pipeline"


def remote(code, timeout=40):
    command = (
        "python3 -c 'import base64;exec(base64.b64decode(\""
        + base64.b64encode(code.encode()).decode()
        + "\"))'"
    )
    text = (
        subprocess.check_output([str(ADB), "shell", command], timeout=timeout)
        .decode(errors="replace")
        .replace("\r", "")
    )
    if any(line.startswith("Traceback (most recent call last):") for line in text.splitlines()):
        raise RuntimeError(text[-8000:])
    return text


def push(local, target):
    subprocess.run([str(ADB), "push", str(local), target], check=True, stdout=subprocess.DEVNULL)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixtures", type=Path, default=ROOT / ".cache/8k-fixtures")
    p.add_argument("--frames", type=int, default=1200)
    p.add_argument("--handover", action="store_true")
    p.add_argument("--resume-stage", help="reuse a completed upload, e.g. run-20261021T010000Z")
    a = p.parse_args()
    tag = a.resume_stage or "run-" + datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    if not re.fullmatch(r"run-[0-9]{8}T[0-9]{6}Z", tag):
        p.error("invalid stage identifier")
    dest = DEST + "/lab8k/" + tag
    output = ROOT / ".cache/8k-lab" / tag
    output.mkdir(parents=True, exist_ok=bool(a.resume_stage))
    manifest = json.loads((a.fixtures / "fixture-manifest.json").read_text())
    assert manifest["scope"] == "SYNTHETIC_CODEC_ONLY" and manifest["width"] == 7680
    print("Staging labelled synthetic inputs; raw NV12 is about 380 MiB.", flush=True)
    remote("from pathlib import Path;Path('" + dest + "').mkdir(parents=True,exist_ok=True)")
    push(ROOT / "board/ffmpeg_pipeline/tests/codec_8k.py", DEST + "/tests/codec_8k.py")
    push(ROOT / "board/ffmpeg_pipeline/tests/codec_metrics.py", DEST + "/tests/codec_metrics.py")
    if not a.resume_stage:
        for file in (
            manifest["raw"]["file"],
            manifest["decode60"]["file"],
            "fixture-manifest.json",
        ):
            push(a.fixtures / file, dest + "/" + file)
    jobs = [
        ("encode30", dest + "/" + manifest["raw"]["file"], False),
        ("decode30", dest + "/encode30/encoded-8k30.mp4", False),
        ("decode60", dest + "/" + manifest["decode60"]["file"], False),
        ("decode60-scale", dest + "/" + manifest["decode60"]["file"], True),
    ]
    results = []
    for label, source, scale in jobs:
        existing = remote(
            "from pathlib import Path;p=Path('"
            + dest
            + "/"
            + label
            + "/result.json');print(p.read_text() if p.is_file() else 'null')"
        )
        if existing.strip() != "null":
            previous = json.loads(existing)
            measurement = previous.get("measurement", {})
            if (
                not previous.get("patternThroughputPassed")
                and measurement.get("exitCode") == 0
                and measurement.get("intervalSeconds", 0) < 5
                and a.frames > measurement.get("frames", 0)
            ):
                label += "-" + str(a.frames)
            else:
                results.append(previous)
                print("Retained previous result " + label, flush=True)
                continue
        print("Running board case " + label + "...", flush=True)
        command = [
            "python3",
            DEST + "/tests/codec_8k.py",
            "--mode",
            label.split("-")[0],
            "--input",
            source,
            "--output",
            dest + "/" + label,
            "--frames",
            str(a.frames),
        ]
        if scale:
            command += ["--display-scale"]
        if a.handover:
            command += ["--handover"]
        code = (
            "import subprocess; p=subprocess.run("
            + repr(command)
            + ',text=True);print("LAB_EXIT="+str(p.returncode))'
        )
        message = remote(code, 240)
        (output / (label + "-console.txt")).write_text(message, encoding="utf-8")
        payload = remote(
            "from pathlib import Path;print(Path('"
            + dest
            + "/"
            + label
            + "/result.json').read_text())"
        )
        result = json.loads(payload)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)
    subprocess.run([str(ADB), "pull", dest, str(output)], check=True, stdout=subprocess.DEVNULL)
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("Local result directory: " + str(output), flush=True)


if __name__ == "__main__":
    main()
