# 当前板端 FFmpeg 链路

性能版本增加 `metrics.py` 后台采样、`decoder.py` 的 VPU/RGA/HDMI 支路，以及增量取帧计数补丁。部署和指标见 [性能指南](../../docs/guides/4K60与性能监测.md)；BSP 候选单独放在 `board/bsp/`，普通部署不会改内核。

对外命令入口保持 `avctl.py`；实现现在位于 `camera_control/`。桌面、操作指南和 systemd 继续调用这个入口，不直接导入内部模块。

8K **实拍**入口为 `tests/imx415_8k.py`，共用计数/进程管理在 `tests/codec_metrics.py`；电脑入口为 `tools/tests/run_imx415_8k.py`。独立 RTSP 配置 `profiles/8k/mediamtx.yml` 使用 8555 端口，实拍路径 `imx415-upscaled-8k30`。[8K 程序清单、实测与命令解释](../../docs/guides/8K_HEVC方案与实测.md) 说明 4K 实拍放大后的 8K30 硬编、实拍来源离线 8K60 文件的硬解，以及原生 8K 的限制。`tests/codec_8k.py` 是上一轮合成基准，本轮实拍不调用它。`check.videoCodecCapabilities` 只报告芯片规格，不等于相机验收。

板端实拍 8K30 硬解/HDMI 支路为 `tests/hdmi_8k.py`，复用 `camera_control/decoder.py` 的 VPU/RGA 实现，使用带时间戳 NUT 管道显示 1080p。电脑通过 `tools/tests/hdmi_imx415_8k.py` 单独启停、查询和下载性能 CSV；该支路不重新打开摄像头、不重启编码器。操作与实际显示丢帧边界见 8K 指南第 9 节。

| 文件 | 责任 | 不负责的内容 |
| --- | --- | --- |
| [avctl.py](avctl.py) | 启动命令行入口 | 不保存直播状态，不自行启动第二个采集器 |
| [camera_control/cli.py](camera_control/cli.py) | 参数解析、读取 stdin JSON、打印结果和退出码 | 不持有摄像头进程 |
| [camera_control/transport.py](camera_control/transport.py) | Unix socket 请求、后台服务、请求互斥与异常包装 | 不配置视频编码参数 |
| [camera_control/controller.py](camera_control/controller.py) | 采集、HDMI、录像、截图、状态与恢复的生命周期 | 不实现 VPU 驱动或 H.265 压缩算法 |
| [camera_control/config.py](camera_control/config.py) | 默认参数、有效范围、错误类型和运行根目录 | 不执行设备操作 |
| [camera_control/support.py](camera_control/support.py) | 时间、日志尾部、原子 JSON、摄像头占用与帧率查询 | 不决定启停策略 |
| [camera_control/raw_scheduler.py](camera_control/raw_scheduler.py) | 可选的 AIQ RAW 线程调度、身份校验及恢复 | 不改变算法线程、IRQ、缓冲数量或固件 |
| [build_runtime.sh](build_runtime.sh)、[versions.json](versions.json) | 固定源码版本、补丁、构建和私有运行库 | 不替换厂商系统库 |
| [install_services.sh](install_services.sh)、[mediamtx.yml](mediamtx.yml) | systemd 和 RTSP 服务配置 | 安装服务不等于自动启用开机启动 |
| `patches/` | FFmpeg NV12M 双平面采集兼容补丁 | 与 Python 控制层分开 |
| `tests/` | 单元、NV12M 和真实链路验收 | 硬件验收脚本会启停管线，区别于单元测试 |

运行目录仍是 `/userdata/av_dev/ffmpeg_pipeline/`。源码模块搬到子目录后，`config.py` 用上一级目录确定运行根目录，避免把配置和录像写到 `camera_control/` 内。

程序有两种运行方式：一次性的 SSH CLI 把请求送到 `state/control.sock`；systemd 启动的 `_serve` 常驻进程拥有 Controller 和子进程。每次查状态不会重新打开相机。

RAW 调度由 `tune_raw_scheduler.py` 显式启用，配置保存在本机 `state/`，不随普通部署默认开启。控制服务只在已启用且 4K、≥50 fps 时，为厂商 AIQ 的三个 RAW 交接线程应用 RR/5；停止、切回低帧率或禁用时恢复。`status.captureScheduling` 报告实际应用状态和错误。操作及验证范围见性能指南；`tests/capture_stability.py` 可对已有直播做只读连续性观察。

本轮源码结构重构没有覆盖当前开发板的运行目录。后续上传时必须同步 `avctl.py` 与整个 `camera_control/`，根目录 `tools/deploy/deploy.ps1` 已按目录递归收集 Python 文件；不要只复制新的入口文件。

运行与接口详解见 [项目程序逻辑](../../docs/architecture/项目程序逻辑与目录导航.md)，实际操作见 [FFmpeg 指南](../../docs/guides/FFmpeg_全链路操作指南.md)。
