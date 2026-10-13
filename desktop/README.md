# EVM3588 Camera Console

Windows 中文桌面客户端：PySide6 界面、Paramiko SSH/SFTP、独立 FFmpeg 解码。使用说明见 [桌面操作指南](../docs/Windows_相机控制台操作指南.md)。免安装 ZIP 在项目根目录本地生成，不提交 Git。

先读 [项目程序逻辑与目录导航](../docs/项目程序逻辑与目录导航.md)，再按 `main.py` → `window.py` → 三个后台 worker 阅读。电脑不导入 Linux 专用板端模块，通过固定 CLI 与 JSON 标准输入交互。

| 模块 | 职责 |
| --- | --- |
| `main.py` | Qt 应用启动、版本与窗口 |
| `evm_console/layout.py` | 首页和四个面板的控件组装、回调绑定 |
| `evm_console/window.py` | 业务协调、控制请求、状态显示和退出 |
| `evm_console/core.py` | 连接模型、配置、按钮条件、结果校验、完整帧拼接 |
| `evm_console/ssh.py` | 后台串行 SSH 操作、状态轮询、指纹、重连 |
| `evm_console/video.py` | 独立 FFmpeg、最新帧邮箱、断流恢复和进程清理 |
| `evm_console/files.py` | 独立 SFTP、文件路径、SHA-256 与下载 |
| `evm_console/playback.py` | 本地 MP4 回放窗口 |
| `evm_console/widgets.py` | 样式、状态卡片、画面绘制 |

本轮为源码结构整理，已发布 EXE 仍为 1.1.0。修改源码不会自动更新已有 ZIP；本轮未重新发布 EXE。

板端安装路径固定为 `/userdata/av_dev/ffmpeg_pipeline/`；RTSP 读取 `8554/imx415`。默认单板单相机。密码和密钥由用户提供，应用退出不停止板端服务。

每条源码运行、测试与打包命令的位置和解释均在操作指南。依赖锁定于 `requirements.lock.txt`；打包说明与依赖许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
