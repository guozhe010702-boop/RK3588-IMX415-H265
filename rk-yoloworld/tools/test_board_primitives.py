"""No camera access: deploy private test binaries, check core/RGA/NUT on ARM64."""

import json, subprocess
from pathlib import Path
from board_link import ROOT, remote, push

DEST = "/userdata/rk-yoloworld-test"


def main():
    print(remote("import os;os.makedirs('" + DEST + "/lib',exist_ok=True)"))
    for name in ["core_tests", "capture_tests", "nut_fixture", "io_smoke", "output_failure_tests"]:
        push(ROOT / "build/arm64-gcc9" / name, DEST + "/" + name)
    for file in (ROOT / "dist/lib").iterdir():
        push(file, DEST + "/lib/" + file.name)
    code = """import os,subprocess,json
os.chdir('/userdata/rk-yoloworld-test')
env=dict(os.environ,LD_LIBRARY_PATH=os.getcwd()+'/lib')
for name in ['core_tests','capture_tests','io_smoke','nut_fixture','output_failure_tests']:os.chmod(name,0o755)
results=[]
for args in [['./core_tests'],['./capture_tests'],['./io_smoke'],['./nut_fixture','variable.nut'],['./output_failure_tests']]:
 p=subprocess.run(args,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30)
 results.append({'command':args,'returncode':p.returncode,'output':p.stdout})
print(json.dumps(results))
"""
    results = json.loads(remote(code, 100))
    (ROOT / "build/board-primitives.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, indent=2))
    assert all(x["returncode"] == 0 for x in results)
    subprocess.run(
        [
            str(__import__("board_link").ADB),
            "pull",
            DEST + "/variable.nut",
            str(ROOT / "build/variable.nut"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_packets",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "json",
            str(ROOT / "build/variable.nut"),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    pts = [float(x["pts_time"]) for x in json.loads(result.stdout)["packets"]]
    assert len(pts) == 5 and all(
        abs(a - b) < 0.0001 for a, b in zip(pts, [0, 0.1, 0.26, 0.3, 0.65])
    ), pts
    print("NUT PTS PASS:", pts)
    subprocess.run(
        [
            str(__import__("board_link").ADB),
            "pull",
            DEST + "/rga-smoke.rgb",
            str(ROOT / "build/rga-smoke.rgb"),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    rgb = (ROOT / "build/rga-smoke.rgb").read_bytes()

    def pixel(x, y):
        return tuple(rgb[(y * 640 + x) * 3 : (y * 640 + x) * 3 + 3])

    colors = [pixel(x, 240) for x in [80, 240, 400, 560]]
    expected = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0)]
    assert all(
        all(abs(a - b) <= 8 for a, b in zip(actual, wanted))
        for actual, wanted in zip(colors, expected)
    ), colors
    assert all(abs(v - 114) <= 3 for v in pixel(100, 20)), pixel(100, 20)
    print("RGA color/letterbox PASS:", colors)


if __name__ == "__main__":
    main()
