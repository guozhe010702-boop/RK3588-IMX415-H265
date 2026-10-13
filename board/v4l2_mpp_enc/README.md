# MPP C API 学习路线

这一目录用于观察从原始图像到压缩码流的过程，当前 Windows 桌面软件通过 FFmpeg 服务控制相机，没有直接调用这些 C 可执行程序。

| 文件 | 从哪里看 |
| --- | --- |
| [v4l2_mpp_enc.c](v4l2_mpp_enc.c) | V4L2 设备打开、格式设置、缓冲区、取帧与释放 |
| [mpp_h265.h](mpp_h265.h) | 公共编码器配置与操作接口 |
| [mpp_h265.c](mpp_h265.c) | MPP 上下文、MppEncCfg、帧输入、码流输出与销毁 |
| [yuv_mpp_enc.c](yuv_mpp_enc.c) | 从 YUV 文件编码，便于分离摄像头问题和编码问题 |
| [Makefile](Makefile) | 编译依赖与目标可执行文件 |

先读 [路线二操作与修改指南](../../docs/路线二_MPP_C_API_操作与修改指南.md)，再按上表阅读。录像、RTSP、多客户端与桌面会话由当前 FFmpeg 产品链路承担；学习用程序不应与产品管线同时占用 `/dev/video44`。
