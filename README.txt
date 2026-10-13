EVM3588-B / IMX415 / FFmpeg H.265 全链路
=======================================

当前：IMX415/con7 → /dev/video44 NV12M → FFmpeg hevc_rkmpp / RK3588 VPU
→ MediaMTX RTSP → HDMI、电脑实时播放，以及手动 MP4 录像、JPEG 截图。
默认 1920x1080 / 30fps / H.265 CBR 2.5Mbit/s / GOP30 / 无音频。

先打开 docs/FFmpeg_全链路操作指南.html。
每条命令标明电脑 PowerShell 或板端 Bash，并解释参数。
实测数据：docs/FFmpeg_全链路验收记录.html。
上位机设计：docs/Windows_上位机设计与开源调研.html；桌面程序下一阶段开发。
MPP C API 学习：docs/路线二_MPP_C_API_操作与修改指南.html。

Windows 上传（项目根目录的电脑 PowerShell）：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
powershell.exe 启动子进程；-NoProfile 不加载个人配置；-ExecutionPolicy Bypass
为本次进程放行；-File 指定上传脚本。上传源码，不自动编译或重启直播。

板端 Bash 查询：
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py status
python3 执行统一入口；status 返回实际状态，不重新打开摄像头。

新程序与私有库在 /userdata/av_dev/ffmpeg_pipeline/。
保留系统 FFmpeg、GStreamer 与 C API；启动前检查摄像头占用。
直播默认不录制，需手动 record-start / record-stop；解释见指南。
浏览器运行状态是手动采样快照，不是实时视频播放器。

修改前备份：backups/before_ffmpeg_fullchain_20261013_093100/。
录像、截图、运行快照、凭据、构建产物与备份不会上传 GitHub。
