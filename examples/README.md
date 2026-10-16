# 学习示例

| 目录 | 用途 |
| --- | --- |
| [mpp_c_api](mpp_c_api/README.md) | V4L2 采集、MPP C API H.265 编码、YUV 文件编码 |
| `gstreamer/` | 原 GStreamer 编码、传输、音视频录像、HDMI + TCP 示例 |

当前主程序使用 `board/ffmpeg_pipeline/`，不会自动调用这些示例。示例与主程序不能同时占用同一个摄像头节点。

部署脚本默认不上传示例；显式选择 `-IncludeExamples` 才上传，`-BuildExamples` 同时上传并编译 MPP 示例。板端兼容路径仍是根目录编号脚本和 `/userdata/av_dev/mpp_route2/`。

阅读 [路线二操作指南](../docs/guides/路线二_MPP_C_API_操作与修改指南.md)，从 PC 源码 `examples/mpp_c_api/` 开始修改。
