# 板端代码导航

现在运行和后续产品开发以 **`ffmpeg_pipeline/`** 为主。`v4l2_mpp_enc/` 用于学习 MPP C API；根目录编号脚本用于原 GStreamer 方案、环境检查和自测。

| 目录或文件 | 定位 | 从哪里开始阅读 |
| --- | --- | --- |
| [ffmpeg_pipeline](ffmpeg_pipeline/README.md) | 当前 FFmpeg 硬编、RTSP、录像、HDMI 控制 | `avctl.py` → `camera_control/cli.py` → `controller.py` |
| [v4l2_mpp_enc](v4l2_mpp_enc/README.md) | V4L2 / MPP C API 学习实现 | `v4l2_mpp_enc.c` → `mpp_h265.h` → `mpp_h265.c` |
| `00_env_check.sh` | 只读环境、工具与摄像头节点检查 | 开发板能力排查 |
| `01_mpp_selftest.sh`、`02_gst_encode_selftest.sh` | MPP 和 GStreamer 自测 | 定位编码器是否可用 |
| `03_cam_encode.sh`、`04_cam_stream.sh`、`05_av_record.sh` | 原 GStreamer 编码、传输、音视频录像示例 | 对照学习与旧方案参考 |
| `07_h265_preview_tcp.sh` | 原 GStreamer tee：HDMI + TCP 裸 H.265 | 已保留的旧实时显示方案 |

编号是旧方案的组织顺序，不是启动当前 FFmpeg 服务需要依次执行的步骤。多个采集程序同时打开同一节点会相互占用；当前产品链路由一个 FFmpeg 采集进程拥有摄像头，播放和录像订阅 RTSP。

目录导航与调用链总图见 [项目程序逻辑](../docs/项目程序逻辑与目录导航.md)。实际上传由根目录 `deploy.ps1` 完成，板端路径为 `/userdata/av_dev/`。
