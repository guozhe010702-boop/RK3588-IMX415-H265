import json
from board_link import ROOT, remote, push

remote("import os;os.makedirs('/userdata/rk-yoloworld-test/rebuilt',exist_ok=True)")
push(
    ROOT / "build/rga-rebuild-gcc9/librga.so.1.10.4",
    "/userdata/rk-yoloworld-test/rebuilt/librga.so.2",
)
print(
    remote(
        """import os,subprocess,json
from pathlib import Path
os.chdir('/userdata/rk-yoloworld-test')
p=subprocess.run(['./io_smoke'],env=dict(os.environ,LD_LIBRARY_PATH=os.getcwd()+'/rebuilt:'+os.getcwd()+'/lib'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
rgb=Path('rga-smoke.rgb').read_bytes()
colors=[tuple(rgb[(240*640+x)*3:(240*640+x)*3+3]) for x in [80,240,400,560]]
assert p.returncode==0,p.stdout
assert all(all(abs(a-b)<=8 for a,b in zip(v,t)) for v,t in zip(colors,[(0,0,0),(255,255,255),(255,0,0),(0,255,0)])),colors
print(json.dumps({'rebuiltRga':True,'colors':colors,'output':p.stdout}))
"""
    )
)
