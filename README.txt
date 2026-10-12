EVM3588-B IMX415 / H.265 实时预览与推流
=====================================

当前已验证硬件：IMX415 接 con7，板端 NV12 采集节点 /dev/video44；
EVM3588-B 的 HDMI 屏幕与电脑 ffplay 可同时观看，板子 IP 曾为 192.168.2.221。

电脑 PowerShell（在本目录执行）：
  powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
这条命令在电脑 PowerShell 运行：powershell 启动子进程，-NoProfile 避免加载用户配置，
-ExecutionPolicy Bypass 仅为这次运行放行脚本，-File 指定部署入口。脚本检查 ADB、上传
Shell 脚本，并把路线二 C 源码放入板端 /userdata/av_dev/mpp_route2/；不会停止当前画面。
如需部署时直接编译，在末尾加 -BuildExamples；板端需有 gcc、make 和 MPP 开发文件。
原板端 /userdata/av_dev/v4l2_mpp_enc/ 不会被覆盖。

板端 Bash：
  cd /userdata/av_dev
  bash 07_h265_preview_tcp.sh --check
--check 只读检查摄像头和 TCP 5000 是否被占用。
当前已有正常预览/推流时，保留该进程即可；不要再启动第二条采集管线。
需要切换到新脚本时，先在原管线终端按 Ctrl+C，然后运行：
  DISPLAY=:0 bash 07_h265_preview_tcp.sh
脚本保持前台运行；Ctrl+C 只结束这条管线。默认分辨率 1920x1080、30fps、TCP 5000。
本次由 ADB 启动的接管实例在后台运行；关闭它前，应先用状态快照或 ss 核对
TCP 5000 的 PID，再仅向该 PID 发送 TERM，不能在新终端按 Ctrl+C 结束它。
可通过 --device、--width、--height、--fps、--port 调整；运行 --help 查看参数。

电脑 PowerShell（板端脚本启动后）：
  ffplay -fflags nobuffer -flags low_delay -f hevc tcp://192.168.2.221:5000
如果 IP 发生变化，在板端用 hostname -I 查看并替换命令中的地址。

本地方案网页的运行状态是手动采样快照。电脑 PowerShell（在 av_dev 根目录）：
  powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh_status.ps1
然后刷新 EVM3588-B_音视频实时压缩方案.html 页面。脚本只读查询 ADB，
输出 board_status.js；页面显示采样时间，不会直接从浏览器控制开发板。

路线二 C API（板端 Bash）：
  cd /userdata/av_dev/mpp_route2
  make
  gst-launch-1.0 -q videotestsrc pattern=smpte num-buffers=30 ! video/x-raw,format=NV12,width=640,height=360,framerate=30/1 ! filesink location=test.nv12
  ./yuv_mpp_enc -i test.nv12 -o test.h265 -w 640 -h 360 -b 1000000 -f 30 -n 30
  ffprobe -v error -f hevc -count_frames -show_entries stream=codec_name,width,height,nb_read_frames -of default=noprint_wrappers=1 test.h265
cd 进入隔离源码目录；make 编译。gst-launch 生成 30 帧 NV12 测试图，-q 减少日志，
num-buffers 指定帧数，filesink 指定输出文件。yuv_mpp_enc 中 -i/-o 是输入/输出，
-w/-h 是宽高，-b 是目标比特率（bit/s），-f 是帧率，-n 是帧数。ffprobe 中
-v error 只打印错误，-f hevc 声明裸 H.265 格式，-count_frames 实际统计帧数，
-show_entries 选择编码、尺寸、帧数字段，-of 设置简洁输出格式。
已实测输出可解码的 30 帧 640x360 HEVC。输出文件若已存在，程序会拒绝覆盖；复测请换新文件名。

摄像头 C API 实测已通过：IMX415 /dev/video44 的双平面 NV12M → V4L2 MMAP →
MppEncCfg H.265 CBR/GOP → encode_put_frame / encode_get_packet，输出 60 帧
1920x1080 HEVC，ffprobe 验证完整。C 程序只录文件；它与 07 主链路不能同时打开摄像头。
复测时先在运行 07 的板端终端按 Ctrl+C，再用 lsof /dev/video44 和
ss -lntp 'sport = :5000' 确认摄像头与端口空闲，然后在上述目录运行：
  ./v4l2_mpp_enc -d /dev/video44 -o imx415_new.h265 -c h265 -w 1920 -h 1080 -b 4000000 -f 30 -n 60
-d 指定采集节点，-o 指定新的码流文件，-c h265 指定编码格式；其余参数同上。
测试完成后在板端运行 DISPLAY=:0 bash /userdata/av_dev/07_h265_preview_tcp.sh 恢复画面。
DISPLAY=:0 选择 HDMI 图形会话，bash 执行预览/推流脚本。电脑 ffplay 断开后重新运行上述命令。

路线三现状：板端 FFmpeg 编码器列表没有 rkmpp；系统头文件/库目录没有 Rockit 开发组件。
libx265 是软件编码器。FFmpeg/Rockit 硬编暂未部署，需要匹配固件的库和构建环境。

旧脚本 00～05 仍在 board/ 下供独立自测。摄像头被占用时不要并行运行采集/录制测试。
