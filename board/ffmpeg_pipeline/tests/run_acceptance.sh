#!/usr/bin/env bash
# Deliberately cycles the live stream. Run only for hardware acceptance.
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$root/build"
trap 'code=$?; printf "{\"exitCode\":%d,\"finishedAt\":\"%s\"}\n" "$code" "$(date -Is)" > "$root/build/acceptance-exit.json"; if ((code)); then python3 "$root/avctl.py" record-stop || true; python3 "$root/avctl.py" start || true; python3 "$root/avctl.py" preview-start || true; fi' EXIT
rm -f "$root/build/acceptance-exit.json" "$root/build/stability-result.json"
python3 -m unittest discover -s "$root/tests" -p 'test_*.py' -v
gcc -std=c11 -Wall -Wextra -Werror "$root/tests/test_nv12m_copy.c" -o "$root/build/test_nv12m_copy"
"$root/build/test_nv12m_copy"
state=$(python3 "$root/avctl.py" status)
if ! python3 -c 'import json,sys; sys.exit(json.loads(sys.argv[1])["result"].get("state")!="running")' "$state"; then
  python3 "$root/avctl.py" start
fi
if ! python3 -c 'import json,sys; sys.exit(not json.loads(sys.argv[1])["result"].get("recording"))' "$state"; then
  python3 "$root/avctl.py" record-start
fi
echo 'PHASE: manual MP4 recording alongside live preview (65 seconds)'
sleep 65
echo 'PHASE: recording finalization, ten start/stop cycles and RTSP restart'
python3 "$root/tests/integration.py"
echo 'PHASE: thirty-minute steady-state monitor'
python3 "$root/tests/stability.py" --seconds 1800
echo 'PHASE: ACCEPTANCE PASSED'
