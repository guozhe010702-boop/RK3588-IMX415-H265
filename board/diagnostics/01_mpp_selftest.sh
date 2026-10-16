#!/bin/bash
#=============================================================================
# MPP 硬件编码器自测 —— 不需要摄像头
# 原理：mpi_enc_test 不指定 -i 输入文件时，内部生成彩条测试图，直接走 VENC 硬编
# 验证：H.264 / H.265 / MJPEG 三路硬件编码是否正常，并统计码率、耗时
# 用法：bash 01_mpp_selftest.sh
#=============================================================================
set -e
OUT=/userdata/mpp_test
mkdir -p $OUT
cd $OUT

# 编码类型：MPP_VIDEO_CodingAVC(H.264)=7  HEVC(H.265)=16777220  MJPEG=8
W=1920; H=1080; N=300    # 1080p, 300帧(约10秒@30fps)

MPI_ENC=$(command -v mpi_enc_test 2>/dev/null || find / -maxdepth 6 -name 'mpi_enc_test' -type f 2>/dev/null | head -1)
if [ -z "$MPI_ENC" ]; then
  echo "[!] 系统未找到 mpi_enc_test。"
  echo "    方案A：用 GStreamer 自测 -> bash 02_gst_encode_selftest.sh"
  echo "    方案B：从 SDK external/mpp 编译（见方案文档第6章 / v4l2_mpp_enc 目录）"
  exit 1
fi
echo "使用编码器测试程序: $MPI_ENC"
echo "================ 支持的编码格式列表 ================"
$MPI_ENC 2>&1 | grep -A40 'coding type support' | head -25 || true
echo "==================================================="

run_enc () {
  local name=$1; local type=$2; local ext=$3
  echo ""
  echo ">>> [$name] ${W}x${H} x ${N}帧 (type=$type) 硬件编码中..."
  local t0=$(date +%s.%N)
  $MPI_ENC -w $W -h $H -t $type -n $N -o $OUT/test_${name}.${ext} 2>&1 | grep -E 'encoded frame|test success|fps|bps|error|ERR' | tail -8
  local t1=$(date +%s.%N)
  local sz=$(stat -c%s $OUT/test_${name}.${ext} 2>/dev/null || echo 0)
  local dt=$(echo "$t1-$t0" | bc 2>/dev/null || echo "?")
  echo "    输出: $OUT/test_${name}.${ext}  大小: $((sz/1024)) KB  耗时: ${dt}s"
  if [ "$sz" -gt 0 ]; then echo "    [OK] $name 硬件编码成功"; else echo "    [失败] $name 无输出"; fi
}

run_enc h264 7      h264
run_enc h265 16777220 h265
run_enc mjpeg 8     mjpg

echo ""
echo "================ 4K(3840x2160) H.265 性能压测 ================"
$MPI_ENC -w 3840 -h 2160 -t 16777220 -n 300 -o $OUT/test_4k.h265 2>&1 | grep -E 'encoded frame|test success|fps' | tail -5
ls -lh $OUT/test_4k.h265 2>/dev/null || true

echo ""
echo "完成。码流文件在 $OUT ，可用 ffplay/VLC 播放，或拷回电脑分析："
echo "  adb pull $OUT/test_h264.h264 ."
