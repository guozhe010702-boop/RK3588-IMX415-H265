#!/bin/bash
#=============================================================================
# EVM3588-B 音视频开发环境自检脚本
# 作用：检查 MPP 硬件编解码 / GStreamer rockchip 插件 / V4L2 摄像头 / RGA / 音频
# 用法：bash 00_env_check.sh
#=============================================================================
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok(){ echo -e "${GREEN}[OK]${NC} $1"; }
no(){ echo -e "${RED}[缺失]${NC} $1"; }
info(){ echo -e "${YELLOW}[信息]${NC} $1"; }

echo "================================================================"
echo " EVM3588-B (RK3588) 音视频环境自检   $(date '+%F %T')"
echo "================================================================"

echo ""
echo "########## 1. 硬件编解码设备节点 ##########"
for d in /dev/mpp_service /dev/rkvenc /dev/rkvdec /dev/vpu_service /dev/rga /dev/dri/renderD128; do
  [ -e "$d" ] && ok "$d 存在" || no "$d 不存在"
done

echo ""
echo "########## 2. MPP 库 ##########"
MPP_LIBS=$(find /usr/lib /lib -name 'librockchip_mpp.so*' 2>/dev/null)
if [ -n "$MPP_LIBS" ]; then echo "$MPP_LIBS"; ok "librockchip_mpp 已安装"; else no "未找到 librockchip_mpp"; fi
find /usr/lib /lib -name 'librga.so*' 2>/dev/null | head -2

echo ""
echo "########## 3. MPP 官方测试程序 (external/mpp/test) ##########"
MPI_ENC=$(command -v mpi_enc_test || find / -maxdepth 6 -name 'mpi_enc_test' -type f 2>/dev/null | head -1)
MPI_DEC=$(command -v mpi_dec_test || find / -maxdepth 6 -name 'mpi_dec_test' -type f 2>/dev/null | head -1)
MPP_INFO=$(command -v mpp_info_test || find / -maxdepth 6 -name 'mpp_info_test' -type f 2>/dev/null | head -1)
[ -n "$MPI_ENC" ] && ok "mpi_enc_test: $MPI_ENC" || info "无 mpi_enc_test（可用 GStreamer 路线，或从 SDK 编译）"
[ -n "$MPI_DEC" ] && ok "mpi_dec_test: $MPI_DEC"
[ -n "$MPP_INFO" ] && { ok "mpp_info_test:"; $MPP_INFO 2>/dev/null | head -8; }
echo "MPI_ENC_PATH=$MPI_ENC" > /tmp/mpp_paths.env
echo "MPI_DEC_PATH=$MPI_DEC" >> /tmp/mpp_paths.env

echo ""
echo "########## 4. GStreamer rockchip 硬件插件 ##########"
if command -v gst-inspect-1.0 >/dev/null 2>&1; then
  gst-launch-1.0 --version | head -1
  for p in mpph264enc mpph265enc mppjpegenc mppvp8enc mppvideodec rkximagesink; do
    if gst-inspect-1.0 $p >/dev/null 2>&1; then ok "插件 $p"; else no "插件 $p 未安装"; fi
  done
  echo "-- 基础插件 --"
  for p in v4l2src videoconvert videoscale h264parse h265parse mp4mux mpegtsmux qtmux autovideosink fakesink alsasrc voaacenc avenc_aac udpsink rtph264pay; do
    gst-inspect-1.0 $p >/dev/null 2>&1 && echo "    $p" || echo "    [缺] $p"
  done
else
  no "未安装 gstreamer-1.0"
fi

echo ""
echo "########## 5. V4L2 视频设备（摄像头/ISP） ##########"
command -v v4l2-ctl >/dev/null 2>&1 && v4l2-ctl --list-devices 2>/dev/null || info "无 v4l2-ctl（apt install v4l-utils）"
echo "-- IMX415 标准节点（con7=video44 con8=video62 con9=video53 con10=video71）--"
for v in 44 53 62 71; do
  [ -e /dev/video$v ] && ok "/dev/video$v" || echo "    /dev/video$v 不存在(未接摄像头时节点仍在,但打不开)"
done

echo ""
echo "########## 6. 音频设备 (es8388) ##########"
cat /proc/asound/cards 2>/dev/null
command -v arecord >/dev/null 2>&1 && arecord -l 2>/dev/null | grep -E 'card|device' | head -8

echo ""
echo "########## 7. 显示/桌面（预览用，无显示器可跳过） ##########"
echo "DISPLAY=$DISPLAY  WAYLAND_DISPLAY=$WAYLAND_DISPLAY  XDG_SESSION_TYPE=$XDG_SESSION_TYPE"

echo ""
echo "########## 8. 性能模式（编码建议 performance） ##########"
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null

echo ""
echo "================================================================"
echo " 自检完成。缺失插件的安装命令："
echo "   apt update"
echo "   apt install -y v4l-utils gstreamer1.0-tools gstreamer1.0-plugins-base \\"
echo "       gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \\"
echo "       gstreamer1.0-rockchip librockchip-mpp1 librockchip-mpp-dev librga-dev"
echo " 若 apt 无 gstreamer1.0-rockchip，则该插件已随固件内置或需从 SDK 编译。"
echo "================================================================"
