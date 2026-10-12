#!/usr/bin/env bash
# IMX415 (con7) -> HDMI preview + H.265 elementary stream over TCP.
# Run in the board's graphical session; Ctrl+C stops only this pipeline.
set -Eeuo pipefail

device=/dev/video44
port=5000
width=1920
height=1080
fps=30

usage() {
  cat <<'EOF'
Usage: bash 07_h265_preview_tcp.sh [--check] [--device /dev/video44] [--port 5000]
                                    [--width 1920] [--height 1080] [--fps 30]

--check reports whether the camera and TCP port are already in use. It does
not open the camera, change its format, or stop the current pipeline.
Start from the board's graphical terminal, or set DISPLAY=:0 in SSH/ADB shell.
On the PC: ffplay -fflags nobuffer -flags low_delay -f hevc tcp://BOARD_IP:PORT
EOF
}

check_integer() {
  [[ "$2" =~ ^[0-9]+$ ]] && (( 10#$2 >= 1 && 10#$2 <= $3 )) || {
    printf 'Invalid %s: %s\n' "$1" "$2" >&2
    exit 2
  }
}

check_only=0
while (($#)); do
  case "$1" in
    --check) check_only=1; shift ;;
    --device|--port|--width|--height|--fps)
      option=$1
      (($# >= 2)) || { usage >&2; exit 2; }
      case "$option" in
        --device) device=$2 ;;
        --port) port=$2 ;;
        --width) width=$2 ;;
        --height) height=$2 ;;
        --fps) fps=$2 ;;
      esac
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

check_integer port "$port" 65535
check_integer width "$width" 16384
check_integer height "$height" 16384
check_integer fps "$fps" 240
[[ "$device" == /dev/video* ]] || { echo 'Device must be /dev/videoN' >&2; exit 2; }

command -v ss >/dev/null || { echo 'Missing command: ss' >&2; exit 1; }
camera_users=''
if command -v fuser >/dev/null; then
  camera_users=$(fuser "$device" 2>/dev/null || true)
elif command -v lsof >/dev/null; then
  camera_users=$(lsof -t "$device" 2>/dev/null || true)
else
  echo 'Need fuser or lsof to check camera ownership.' >&2
  exit 1
fi
port_users=$(ss -H -lntp "sport = :$port" 2>/dev/null || true)

printf 'Camera: %s\nTCP port: %s\n' "$device" "$port"
if [[ -n "$camera_users" ]]; then printf 'Camera in use by PID(s): %s\n' "$camera_users"; fi
if [[ -n "$port_users" ]]; then printf 'TCP port in use: %s\n' "$port_users"; fi
if (( check_only )); then
  if [[ -z "$camera_users" && -z "$port_users" ]]; then echo 'Camera and TCP port are available.'; fi
  exit 0
fi

[[ -e "$device" ]] || { printf 'Camera node not found: %s\n' "$device" >&2; exit 1; }
[[ -z "$camera_users" && -z "$port_users" ]] || {
  echo 'Stop the existing pipeline in its own terminal before starting another one.' >&2
  exit 1
}
[[ -n "${DISPLAY:-}" ]] || {
  echo 'DISPLAY is empty. Run from the HDMI desktop terminal, or set DISPLAY=:0.' >&2
  exit 1
}
for element in v4l2src tee queue videoconvert autovideosink mpph265enc h265parse tcpserversink; do
  gst-inspect-1.0 "$element" >/dev/null 2>&1 || {
    printf 'Missing GStreamer element: %s\n' "$element" >&2
    exit 1
  }
done

echo 'Starting HDMI preview and H.265 TCP server. Press Ctrl+C to stop.'
printf 'PC command: ffplay -fflags nobuffer -flags low_delay -f hevc tcp://BOARD_IP:%s\n' "$port"
exec gst-launch-1.0 -v \
  v4l2src "device=$device" \
  '!' "video/x-raw,format=NV12,width=$width,height=$height,framerate=$fps/1" \
  '!' tee name=t \
  t. '!' queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream \
     '!' videoconvert '!' autovideosink sync=false \
  t. '!' queue \
     '!' mpph265enc \
     '!' h265parse config-interval=-1 \
     '!' video/x-h265,stream-format=byte-stream,alignment=au \
     '!' tcpserversink host=0.0.0.0 "port=$port" sync=false
