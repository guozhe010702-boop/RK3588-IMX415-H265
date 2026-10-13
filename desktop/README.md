# EVM3588 Camera Console

Windows 中文桌面客户端：PySide6 界面、Paramiko SSH/SFTP、独立 FFmpeg 解码。使用说明见 [桌面操作指南](../docs/Windows_相机控制台操作指南.md)。免安装 ZIP 在项目根目录本地生成，不提交 Git。

业务分成 `evm_console/core.py`（模型）、`ssh.py`（控制）、`video.py`（最新帧预览）、`files.py`（文件）和 `window.py` / `widgets.py`（界面）。电脑不导入 Linux 专用板端模块，通过固定 CLI 与 JSON 标准输入交互。

板端安装路径固定为 `/userdata/av_dev/ffmpeg_pipeline/`；RTSP 读取 `8554/imx415`。默认单板单相机。密码和密钥由用户提供，应用退出不停止板端服务。

每条源码运行、测试与打包命令的位置和解释均在操作指南。依赖锁定于 `requirements.lock.txt`；打包说明与依赖许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
