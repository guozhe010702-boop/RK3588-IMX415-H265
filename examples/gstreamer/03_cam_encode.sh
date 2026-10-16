#!/bin/bash
#=============================================================================
# 摄像头实时采集 -> RGA/硬编 -> H.264/H.265 -> MP4 文件（可同时本地预览）
# 硬件：IMX415  MIPI CSI  con7=/dev/video44  con8=/dev/video62
#                              con9=/dev/video53  con10=/dev/video71
# 用法:
#   bash 03_cam_encode.sh [video节点] [编码] [宽x高] [码率Mbps] [时长秒]
# 示例:
#   bash 03_cam_encode.sh 44 h264 1920x1080 4  20      # con7 1080p H264 录20秒
#   bash 03_cam_encode.sh 44 h265 3840x2160 12 0       # con7 4K H265 一直录(Ctrl+C停)
#=============================================================================
DEV=${1:-44}
CODEC=${2:-h264}
RES=${3:-1920x1080}
BPS_MB=${4:-4}
DUR=${5:-0}          # 0=持续录制直到 Ctrl+C
W=${RES%x*}; H=${RES#*x}
BPS=$((BPS_MB*1000000))
OUT=/userdata/cam_${CODEC}_${RES}_$(date +%H%M%S).mp4
mkdir -p /userdata

# 时长控制：0 用 num-buffers 限制
DURCMD=""; [ "$DUR" -gt 0 ] && DURCMD="num-buffers=$((DUR*30))"

case $CODEC in
  h264) ENC=mpph264enc; PARSE=h264parse ;;
  h265) ENC=mpph265enc; PARSE=h265parse ;;
  *) echo "编码只支持 h264 / h265"; exit 1 ;;
esac

echo "============================================================"
echo " 设备 /dev/video$DEV | $CODEC | ${W}x${H}@30 | 码率 ${BPS_MB}Mbps"
echo " 输出 $OUT"
echo " 有显示器会弹预览窗；无显示器自动切换 fakesink"
echo "============================================================"

# 是否有图形环境
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then SINK=autovideosink; else SINK=fakesink; fi
echo "显示支路: $SINK"

# tee 分两路：一路硬编存盘，一路预览。queue 防止卡死。
gst-launch-1.0 -e \
  v4l2src device=/dev/video$DEV $DURCMD \
  ! video/x-raw,format=NV12,width=$W,height=$H,framerate=30/1 \
  ! tee name=t \
  t. ! queue max-size-buffers=2 leaky=downstream \
       ! $ENC rc-mode=cbr bps=$BPS gop=30 \
       ! $PARSE ! mp4mux faststart=true ! filesink location=$OUT \
  t. ! queue max-size-buffers=2 leaky=downstream \
       ! videoconvert ! $SINK sync=false

echo ""
echo "录制结束: $OUT"
ls -lh $OUT 2>/dev/null
echo "拷回电脑: adb pull $OUT ."
