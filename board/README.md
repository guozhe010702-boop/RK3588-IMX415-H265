# 板端主程序

| 目录 | 用途 |
| --- | --- |
| [ffmpeg_pipeline](ffmpeg_pipeline/README.md) | 当前 FFmpeg / VPU、RTSP、MP4、HDMI 控制；入口 avctl.py |
| `diagnostics/` | 00 环境检查、01 MPP 自测、02 GStreamer 编码自测 |

学习源码已从这里移出，见 [examples](../examples/README.md)。当前主程序只维护 ffmpeg_pipeline；诊断脚本不是启动顺序。

部署入口在 `tools/deploy/deploy.ps1`，板端运行位置保持 `/userdata/av_dev/ffmpeg_pipeline/`。完整调用链见 [程序逻辑](../docs/architecture/项目程序逻辑与目录导航.md)。
