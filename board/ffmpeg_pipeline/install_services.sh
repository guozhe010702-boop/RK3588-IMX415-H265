#!/usr/bin/env bash
set -Eeuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $EUID == 0 ]] || { echo 'Install services as root'; exit 1; }
[[ -x "$root/runtime/bin/ffmpeg" && -x "$root/runtime/bin/mediamtx" ]] || { echo 'Build runtime first'; exit 1; }
mkdir -p "$root/state" "$root/logs" "$root/recordings" "$root/snapshots"
[[ -f "$root/config.json" ]] || cp "$root/config.example.json" "$root/config.json"
cat > /etc/systemd/system/evm-mediamtx.service <<EOF
[Unit]
Description=EVM3588 isolated RTSP relay
After=network.target

[Service]
Type=simple
WorkingDirectory=$root
ExecStart=$root/runtime/bin/mediamtx $root/mediamtx.yml
Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/evm-ffmpeg-control.service <<EOF
[Unit]
Description=EVM3588 FFmpeg camera controller
After=evm-mediamtx.service
Wants=evm-mediamtx.service

[Service]
Type=simple
WorkingDirectory=$root
ExecStart=/usr/bin/python3 $root/avctl.py _serve
Restart=on-failure
RestartSec=2
KillSignal=SIGINT
TimeoutStopSec=25
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
echo 'Service files installed. They are not enabled for automatic boot startup.'
