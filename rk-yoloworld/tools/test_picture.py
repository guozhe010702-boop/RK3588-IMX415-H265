"""Real NPU picture parity + changed class list, without using the camera."""

import json
from board_link import ROOT, remote, push


def main():
    dest = "/userdata/rk-yoloworld"
    push(ROOT / "build/arm64-gcc9/picture_parity", dest + "/picture_parity")
    push(ROOT / "build/bus640.rgb", dest + "/bus640.rgb")
    code = """import os,subprocess,json
os.chdir('/userdata/rk-yoloworld');os.chmod('picture_parity',0o755)
p=subprocess.run(['./picture_parity','bus640.rgb'],env=dict(os.environ,LD_LIBRARY_PATH=os.getcwd()+'/lib'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=240)
print(json.dumps({'returncode':p.returncode,'output':p.stdout}))
"""
    data = json.loads(remote(code, 260))
    (ROOT / "build/picture-parity.json").write_text(json.dumps(data, indent=2))
    print("returncode=", data["returncode"])
    print("\n".join(s for s in data["output"].splitlines() if s.startswith("{")))
    assert data["returncode"] == 0, data["output"][-2000:]


if __name__ == "__main__":
    main()
