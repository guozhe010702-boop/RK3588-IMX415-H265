"""Read ignored board test logs and process state; never sends control commands."""

from board_link import remote

print(
    remote(
        """from pathlib import Path
import json,os
r=Path('/userdata/rk-yoloworld');pid=(r/'state/test-wrapper.pid').read_text().strip();active=Path('/proc/'+pid).exists()
files=sorted((r/'logs').glob('*.jsonl')) if (r/'logs').exists() else []
last=files[-1] if files else None
lines=last.read_text().splitlines() if last else []
errors=last.with_suffix('.log').read_text().splitlines()[-7:] if last else []
print(json.dumps({'active':active,'log':str(last),'samples':len(lines),'last':lines[-2:],'errors':errors,'wrapperTail':(r/'state/test-wrapper.log').read_text().splitlines()[-3:]}))
"""
    )
)
