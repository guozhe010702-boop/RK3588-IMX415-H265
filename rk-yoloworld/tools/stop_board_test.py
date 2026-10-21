from board_link import remote

print(
    remote(
        """from pathlib import Path
import os,signal,json
p=Path('/userdata/rk-yoloworld/state/test-wrapper.pid');pid=int(p.read_text());cmd=Path('/proc/'+str(pid)+'/cmdline').read_bytes()
assert b'run_with_restore.py' in cmd
os.kill(pid,signal.SIGINT);print(json.dumps({'stopRequested':pid}))
"""
    )
)
