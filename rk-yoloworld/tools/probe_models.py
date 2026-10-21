"""Probe private model compatibility on the board without opening the camera."""

import json, sys
from board_link import ROOT, remote, push

DEST = "/userdata/rk-yoloworld"


def main():
    remote("import os;os.makedirs('" + DEST + "',exist_ok=True)")
    for file in (ROOT / "dist").rglob("*"):
        if file.is_file():
            dest = DEST + "/" + file.relative_to(ROOT / "dist").as_posix()
            remote(
                "import os;os.makedirs("
                + repr(str(__import__("posixpath").dirname(dest)))
                + ",exist_ok=True)"
            )
            push(file, dest)
    fixture = ROOT / "build/bus640.rgb"
    arguments = ["./rknn_yolo_world_realtime", "--probe"]
    if fixture.exists():
        push(fixture, DEST + "/bus640.rgb")
        arguments += ["--verify-rgb", "bus640.rgb"]
    code = """import os,subprocess,json
os.chdir('/userdata/rk-yoloworld')
os.chmod('rknn_yolo_world_realtime',0o755)
p=subprocess.run(ARGS,env=dict(os.environ,LD_LIBRARY_PATH=os.getcwd()+'/lib'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
print(json.dumps({'returncode':p.returncode,'output':p.stdout}))
""".replace(
        "ARGS", repr(arguments)
    )
    text = remote(code, 260)
    data = json.loads(text)
    (ROOT / "build/model-probe.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("returncode=", data["returncode"])
    print("\n".join(data["output"].splitlines()[-4:]))
    return data["returncode"]


if __name__ == "__main__":
    sys.exit(main())
