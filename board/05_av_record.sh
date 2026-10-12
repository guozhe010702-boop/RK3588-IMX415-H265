#!/bin/bash
#=============================================================================
# 摄像头视频(MPP硬编) + 麦克风音频(ALSA采集/AAC) 同步录制为 MP4
# 音频芯片: es8388（耳机/麦克风口，手册5.5节）
# 用法: bash 05_av_record.sh [video节点] [时长秒] [分辨率]
#   bash 05_av_record.sh 44 20 1920x1080
#=============================================================================
DEV=${1:-44}; DUR=${2:-20}; RES=${3:-1920x1080}
W=${RES%x*}; H=${RES#*x}
OUT=/userdata/av_record_$(date +%H%M%S).mp4
FRAMES=$((DUR*30))

# ---- 自动探测音频采集设备 ----
ACARD=$(arecord -l 2>/dev/null | awk '/card [0-9]+:/{print $2; exit}' | tr -d ':')
if [ -z "$ACARD" ]; then echo "[!] 未发现音频采集设备（未接麦克风/耳机口）"; AUDIO=""; else
  echo "检测到音频卡: $ACARD"
  # AAC 编码器二选一
  if gst-inspect-1.0 voaacenc >/dev/null 2>&1; then AENC="voaacenc ! aacparse";
  elif gst-inspect-1.0 avenc_aac >/dev/null 2>&1; then AENC="avenc_aac ! aacparse";
  else echo "[!] 无 AAC 编码器，安装: apt install gstreamer1.0-plugins-ugly"; AUDIO=""; fi
  [ -n "$AENC" ] && AUDIO="alsasrc device=hw:$ACARD,0 ! audio/x-raw,rate=44100,channels=2 ! audioconvert ! $AENC ! queue ! mux."
fi

echo "============================================================"
echo " 视频 /dev/video$DEV ${W}x${H}@30 -> H.264 硬编"
[ -n "$AUDIO" ] && echo " 音频 hw:$ACARD,0 -> AAC"
echo " 输出 $OUT  时长 ${DUR}s"
echo "============================================================"

gst-launch-1.0 -e \
  v4l2src device=/dev/video$DEV num-buffers=$FRAMES \
  ! video/x-raw,format=NV12,width=$W,height=$H,framerate=30/1 \
  ! mpph264enc rc-mode=cbr bps=4000000 gop=30 ! h264parse ! queue \
  ! mp4mux name=mux faststart=true ! filesink location=$OUT \
  $AUDIO

echo ""; ls -lh $OUT 2>/dev/null
echo "纯音频测试(不含视频)可用: arecord -D plughw:$ACARD,0 -f cd -d 5 /tmp/a.wav"
