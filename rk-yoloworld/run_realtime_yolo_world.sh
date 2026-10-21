#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH=./lib:${LD_LIBRARY_PATH:-}
source ./config.env
for file in rknn_yolo_world_realtime lib/librknnrt.so lib/librga.so.2 model/clip_text_fp16.rknn model/yolo_world_v2s_i8.rknn model/detect_classes.txt; do
  [[ -s "$file" ]] || { echo "Missing required file: $file" >&2; exit 2; }
done
[[ -x "$FFMPEG" ]] || { echo 'Private FFmpeg not found; set FFMPEG in config.env.' >&2; exit 2; }
# Encoder has a separate library environment, never inherits the model runtime.
LD_LIBRARY_PATH="$FFMPEG_LIB" "$FFMPEG" -hide_banner -encoders 2>/dev/null | grep 'h264_rkmpp' >/dev/null || { echo 'h264_rkmpp is unavailable; refusing software fallback.' >&2; exit 2; }
probe=false
for arg in "$@"; do [[ "$arg" == '--probe' || "$arg" == '--verify-rgb' || "$arg" == '--help' ]] && probe=true; done
if ! $probe; then
  if command -v fuser >/dev/null && fuser "$DEVICE" >/dev/null 2>&1; then
    echo "Camera busy: $DEVICE. Existing owners (no processes were terminated):" >&2
    fuser -v "$DEVICE" >&2 || true
    exit 3
  fi
fi
# exec gives SIGINT/SIGTERM directly to the application. It owns and reaps FFmpeg.
exec ./rknn_yolo_world_realtime --device "$DEVICE" --width "$WIDTH" --height "$HEIGHT" --fps "$FPS" \
  --buffers "$BUFFERS" --skip "$SKIP" --capture-priority "${CAPTURE_PRIORITY:-0}" --bitrate "$BITRATE" --gop "$GOP" --url "$DESTINATION" \
  --ffmpeg "$FFMPEG" --ffmpeg-lib "$FFMPEG_LIB" "$@"
