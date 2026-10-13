# RK3588 / IMX415 / FFmpeg H.265 实时链路

IMX415 接 EVM3588-B con7，经 `/dev/video44` 双平面 NV12M 采集，由独立 FFmpeg 的 `hevc_rkmpp` 调用 RK3588 VPU 编码，MediaMTX 分发 RTSP。开发板 HDMI 与电脑同时播放；手动 MP4 录像使用流复制，无二次编码，支持 JPEG 截图和运行统计。

默认 1920×1080、30 fps、H.265 CBR 2.5 Mbit/s、GOP 30、无音频。保留系统 FFmpeg、厂商 MPP/RGA/ISP 服务、GStreamer 方案和路线二 C 程序。验收后保持新链路运行，未启用开机自动启动。

**Windows 桌面控制台已实现。** 解压本地 `EVM3588CameraConsole-Windows-x64-v1.1.0.zip`，双击 EXE，通过中文界面连接 SSH、实时看画面、选择 H.264/H.265、控制 HDMI、截图、录像、下载与回放。无需安装 Python，首次登录使用自己的 SSH 密码或密钥。

先阅读 [桌面操作指南](docs/Windows_相机控制台操作指南.md)；测试数据见 [桌面验收记录](docs/Windows_相机控制台验收记录.md)。新增预览档位、会话隔离、下载内容校验与异步退出，见 [1.1.0 优化调研](docs/Windows_控制台优化调研与实施.md)。源码位于 [desktop](desktop/README.md)，便携 EXE 在本地交付，不上传 Git。

| 内容 | 入口 |
| --- | --- |
| 部署、构建、播放、录像、截图、故障处理 | [FFmpeg 全链路操作指南](docs/FFmpeg_全链路操作指南.md) |
| 实测数据与边界 | [全链路验收记录](docs/FFmpeg_全链路验收记录.md) |
| Windows 上位机下一阶段设计 | [设计与开源调研](docs/Windows_上位机设计与开源调研.md) |
| 方案与采样状态网页 | [方案网页](EVM3588-B_音视频实时压缩方案.html)，下载后本地打开 |
| 统一控制接口 | [avctl.py](board/ffmpeg_pipeline/avctl.py) |
| 版本锁定与构建 | [versions.json](board/ffmpeg_pipeline/versions.json)、[build_runtime.sh](board/ffmpeg_pipeline/build_runtime.sh) |
| NV12M 兼容补丁 | [patches](board/ffmpeg_pipeline/patches/0001-nv12m-capture.patch) |
| V4L2 与 MPP C API 学习 | [路线二指南](docs/路线二_MPP_C_API_操作与修改指南.md) |

## 操作入口

电脑 PowerShell，在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

`powershell.exe` 启动子进程；`-NoProfile` 避免加载个人配置；`-ExecutionPolicy Bypass` 仅为本次运行放行；`-File` 指定脚本。上传源码，不自动重建或切换管线。首次使用还需按完整指南构建和安装板端服务。

开发板 Bash，查询状态：

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py status
```

`python3` 执行统一入口；`status` 返回实际采集进程、编码器、VPU 访问、帧进度、RTSP、HDMI 和录像状态，不重新占用摄像头。

电脑 PowerShell，直播启动后播放：

```powershell
ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay rtsp://192.168.2.221:8554/imx415
```

`ffplay` 播放实时流；`-rtsp_transport tcp` 使用 TCP；后两组选项减少缓冲；URL 中替换成实际板子 IP。完整指南解释每条构建和控制命令。

## 实测范围与后续工作

本轮使用 H.265 进行真实硬编、两端显示、MP4 回放、截图、十次启停、服务重启与连续运行验收。时间、帧数、资源数据见验收记录。连接到首帧的时间不等于镜头到屏幕的端到端延迟，后者尚未测量。

Windows 桌面软件已实现并接入板端控制接口，H.264/H.265 切换已实际出画面，持续验收使用 H.265。曝光/增益与 RKAIQ 协调、ROI、算法识别、音频、外网和多路相机待后续开发。

网页状态由电脑 [refresh_status.ps1](refresh_status.ps1) 手动生成并注明采样时间；浏览器本身不连接 SSH、不直接播放 RTSP。运行快照、录像、截图、凭据、备份与构建产物保留本地，不上传 Git。`音视频代码包/` 与 ZIP 是本地交付副本，Git 以根目录 `board/` 为准；厂商 SDK 不入仓库。

修改前备份在 `backups/before_ffmpeg_fullchain_20261013_093100/`，包含 Git bundle 和旧方案。上游组件许可证以其源码为准，本项目未另行声明整体开源许可证。
