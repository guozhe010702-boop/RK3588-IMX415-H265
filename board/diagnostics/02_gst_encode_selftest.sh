#!/bin/bash
#=============================================================================
# GStreamer 硬件编码自测 —— 不需要摄像头
# 用 videotestsrc 生成测试图案，经 mpph264enc/mpph265enc 走 VENC 硬编
# 用法：bash 02_gst_encode_selftest.sh
#=============================================================================
OUT=/userdata/gst_test; mkdir -p $OUT; cd $OUT
FRAMES=300    # 300帧 @30fps = 10秒

# 检测 rockchip 硬编插件
H264ENC="mpph264enc"; H265ENC="mpph265enc"
gst-inspect-1.0 mpph264enc >/dev/null 2>&1 || { echo "[!] 无 mpph264enc 插件，先运行 00_env_check.sh 并按提示安装"; exit 1; }

echo "############ 1. H.264 硬编 1080p30 -> MP4 ############"
gst-launch-1.0 -e videotestsrc num-buffers=$FRAMES \
  ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 \
  ! $H264ENC rc-mode=cbr bps=4000000 gop=30 \
  ! h264parse ! mp4mux ! filesink location=$OUT/test_1080p_h264.mp4 2>&1 | tail -4
ls -lh $OUT/test_1080p_h264.mp4 2>/dev/null

echo ""
echo "############ 2. H.265 硬编 1080p30 -> MP4 ############"
gst-launch-1.0 -e videotestsrc num-buffers=$FRAMES \
  ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 \
  ! $H265ENC rc-mode=cbr bps=3000000 gop=30 \
  ! h265parse ! mp4mux ! filesink location=$OUT/test_1080p_h265.mp4 2>&1 | tail -4
ls -lh $OUT/test_1080p_h265.mp4 2>/dev/null

echo ""
echo "############ 3. 4K30 H.265 硬编性能压测 -> TS ############"
gst-launch-1.0 -e videotestsrc num-buffers=300 \
  ! video/x-raw,format=NV12,width=3840,height=2160,framerate=30/1 \
  ! $H265ENC rc-mode=cbr bps=12000000 gop=30 \
  ! h265parse ! mpegtsmux ! filesink location=$OUT/test_4k_h265.ts 2>&1 | tail -4
ls -lh $OUT/test_4k_h265.ts 2>/dev/null

echo ""
echo "############ 4. 实时帧率统计（fakesink，看硬编吞吐） ############"
echo "--- H.264 1080p ---"
GST_DEBUG=fpsdisplaysink:5 gst-launch-1.0 videotestsrc num-buffers=300 \
  ! video/x-raw,format=NV12,width=1920,height=1080,framerate=30/1 \
  ! $H264ENC ! fakesink sync=false 2>&1 | grep -iE 'fps|last' | tail -3
echo "--- H.265 4K ---"
GST_DEBUG=fpsdisplaysink:5 gst-launch-1.0 videotestsrc num-buffers=300 \
  ! video/x-raw,format=NV12,width=3840,height=2160,framerate=30/1 \
  ! $H265ENC ! fakesink sync=false 2>&1 | grep -iE 'fps|last' | tail -3

echo ""
echo "完成，文件在 $OUT。播放：gst-play-1.0 test_1080p_h264.mp4"
