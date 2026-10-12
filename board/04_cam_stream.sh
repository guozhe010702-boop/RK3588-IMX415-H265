#!/bin/bash
#=============================================================================
# 摄像头实时采集 -> 硬编 -> 网络推流（低延迟）
# 方式A(默认,最省事): UDP + MPEG-TS，电脑端 VLC 打开  udp://@:5000
# 方式B: RTSP，需板端有 gst-rtsp-server(test-launch)，脚本会自动探测
#
# 用法:
#   bash 04_cam_stream.sh udp  [电脑IP] [video节点] [编码] [分辨率]
#   bash 04_cam_stream.sh rtsp [video节点] [编码] [分辨率]
# 示例:
#   bash 04_cam_stream.sh udp 192.168.2.165 44 h264 1920x1080
#   电脑端 VLC -> 媒体 -> 打开网络串流 -> udp://@:5000
#=============================================================================
MODE=${1:-udp}
if [ "$MODE" = "udp" ]; then
  HOST=${2:-192.168.2.165}; PORT=5000
  DEV=${3:-44}; CODEC=${4:-h264}; RES=${5:-1920x1080}
else
  DEV=${2:-44}; CODEC=${3:-h264}; RES=${4:-1920x1080}
fi
W=${RES%x*}; H=${RES#*x}
case $CODEC in
  h264) ENC=mpph264enc; PARSE=h264parse; PAY=rtph264pay ;;
  h265) ENC=mpph265enc; PARSE=h265parse; PAY=rtph265pay ;;
  *) echo "编码只支持 h264/h265"; exit 1 ;;
esac

if [ "$MODE" = "udp" ]; then
  echo ">>> UDP/TS 推流 -> $HOST:$PORT （${W}x${H} $CODEC）"
  echo "    电脑 VLC 打开: udp://@:$PORT"
  # 低延迟：CBR + 短GOP + 关闭B帧由编码器默认；TS over UDP
  gst-launch-1.0 -e \
    v4l2src device=/dev/video$DEV \
    ! video/x-raw,format=NV12,width=$W,height=$H,framerate=30/1 \
    ! $ENC rc-mode=cbr bps=4000000 gop=15 \
    ! $PARSE ! mpegtsmux alignment=7 \
    ! udpsink host=$HOST port=$PORT sync=false buffer-size=65536
else
  TL=$(command -v test-launch || find / -maxdepth 6 -name test-launch -type f 2>/dev/null | head -1)
  if [ -z "$TL" ]; then
    echo "[!] 未找到 gst-rtsp-server 的 test-launch。"
    echo "    请用 UDP 方式，或在 X86 Ubuntu 主机交叉编译 gst-rtsp-server（SDK 含 gst 源码）。"
    echo "    编译后 test-launch 命令示例："
    cat <<EOF
  ./test-launch "( v4l2src device=/dev/video$DEV \\
    ! video/x-raw,format=NV12,width=$W,height=$H,framerate=30/1 \\
    ! $ENC ! $PARSE ! $PAY name=pay0 pt=96 )"
  # 电脑 VLC 打开 rtsp://<板子IP>:8554/test
EOF
    exit 1
  fi
  echo ">>> RTSP 服务启动: rtsp://$(hostname -I | awk '{print $1}'):8554/test"
  $TL "( v4l2src device=/dev/video$DEV ! video/x-raw,format=NV12,width=$W,height=$H,framerate=30/1 ! $ENC ! $PARSE ! $PAY name=pay0 pt=96 )"
fi
