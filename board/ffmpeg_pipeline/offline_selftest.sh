#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export LD_LIBRARY_PATH="$root/runtime/lib:$root/runtime/lib64"
output="$root/build/offline-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$output"
"$root/runtime/bin/ffmpeg" -hide_banner -nostdin -loglevel info -re -f lavfi -i testsrc2=size=640x360:rate=30 -vf format=nv12 -frames:v 60 -c:v hevc_rkmpp -rc_mode CBR -b:v 1000000 -g 30 -bf 0 -n "$output/test.mp4" > "$output/stdout.log" 2> "$output/encode.log" &
encode_pid=$!
sleep 1
ls -l "/proc/$encode_pid/fd" > "$output/vpu-fds.txt"
wait "$encode_pid"
"$root/runtime/bin/ffprobe" -v error -count_frames -show_entries stream=codec_name,width,height,nb_read_frames -of json "$output/test.mp4" > "$output/probe.json"
python3 - "$output" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); stream=json.loads((p/'probe.json').read_text())['streams'][0]
assert stream['codec_name']=='hevc' and stream['width']==640 and stream['height']==360 and stream['nb_read_frames']=='60',stream
assert '/dev/mpp_service' in (p/'vpu-fds.txt').read_text(), 'VPU device not open'
print(json.dumps({'ok':True,'output':str(p),'probe':stream,'vpuDeviceOpen':True}))
PY
