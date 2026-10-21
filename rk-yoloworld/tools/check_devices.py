from board_link import remote

print(
    remote(
        """from pathlib import Path
import json
rows=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  cmd=(p/'cmdline').read_bytes().split(b'\\0')
  if not cmd:continue
  is_app=cmd[0].endswith(b'rknn_yolo_world_realtime')
  is_encoder=cmd[0].endswith(b'ffmpeg') and b'h264_rkmpp' in cmd
  if not (is_app or is_encoder):continue
  libraries=sorted({s.split()[-1] for s in (p/'maps').read_text().splitlines() if 'librga' in s or 'librknnrt' in s})
  devices=[]
  for fd in (p/'fd').glob('*'):
   try:
    target=str(fd.resolve(strict=True))
    if target.startswith('/dev/') and ('mpp' in target or 'rkv' in target or 'video44' in target):devices.append(target)
   except OSError:pass
  rows.append({'pid':int(p.name),'application':is_app,'libraries':libraries,'devices':sorted(set(devices)),'tasks':len(list((p/'task').iterdir()))})
 except OSError:pass
print(json.dumps(rows))
"""
    )
)
