# Windows 相机控制台：安装、操作与源码修改

版本 1.2.0。中文深色桌面软件，主界面为实时视频，右侧为设备连接、编码设置、媒体文件、运行日志和性能监测。新增指标与 CSV 见 [4K60 与性能监测](4K60与性能监测.md)。硬编在 RK3588，电脑负责控制、解码与下载。4K60 预设不代表当前传感器已支持。

## 1. 双击使用免安装版

本地交付文件是`releases/EVM3588CameraConsole-Windows-x64-v1.2.0.zip`，其 `.zip.sha256` 文件保存校验值。解压整个压缩包，进入 `EVM3588CameraConsole` 文件夹，双击 `EVM3588CameraConsole.exe`。

保留 EXE、`_internal/`、`ffmpeg/`、许可说明和版本记录之间的相对位置。无需安装 Python；不要只把 EXE 单独拖到其它目录。可把 EXE 的快捷方式放在桌面。

若采用终端解压，**电脑 PowerShell，项目根目录**：

```powershell
Expand-Archive -LiteralPath '.\releases\EVM3588CameraConsole-Windows-x64-v1.2.0.zip' -DestinationPath '.\桌面控制台'
```

解释：`Expand-Archive` 解压 ZIP；`-LiteralPath` 按原样处理输入文件名；`-DestinationPath` 指定新目录。本示例目标目录应尚未使用，重复解压请换新目录。

```powershell
Start-Process -FilePath '.\桌面控制台\EVM3588CameraConsole\EVM3588CameraConsole.exe'
```

解释：`Start-Process` 启动可见的桌面程序；`-FilePath` 指向解压后的 EXE。这条命令在电脑执行，不能在开发板 Bash 中运行。

## 2. 第一次连接

1. 保持板子通电，电脑与板子处于可互通的局域网。
2. 在“设备连接”填写板子地址，当前为 `192.168.2.221`；SSH 端口默认 22，用户名默认 root。
3. 选择密码登录，填写自己已有的 SSH 密码；或选择密钥登录并选择自己的私钥，按需填写私钥口令。
4. 点击“连接开发板”，核对弹出的 SSH 主机指纹，确认后保存。指纹改变时软件拒绝连接，需要先查明板子身份或重刷系统的情况。
5. 软件读取板端能力与状态。已有直播时直接显示，不重复启动摄像头采集。

“记住密码”可选择使用 Windows 凭据管理器保存；配置文件不保存明文密码。软件验收使用的临时密钥不会随包交付，使用时应输入自己的认证信息。

如果忘记 SSH 密码但仍能通过 ADB 登录，**电脑 PowerShell，项目根目录**：

```powershell
$adbPath = 'C:\Users\dvsense_docker\Desktop\work\RK3588\Tools\platform-tools\adb.exe'
```

解释：保存本机 ADB 路径，其它电脑替换成真实路径。

```powershell
& $adbPath shell
```

解释：`&` 执行 ADB；`shell` 进入开发板 Bash。下一条命令在出现 `root@ema` 后执行。

**开发板 Bash，仅在自己需要设置新密码时**：

```bash
passwd root
```

解释：为 root 账户交互设置新密码，需要输入两次；终端不回显密码。它会改变原有密码，因此已有可用 SSH 认证时不需要执行。密码在本地输入，不要发到聊天或提交到 Git。

## 3. 看画面、HDMI 与状态卡片

连接成功且直播运行后，中央显示实时画面。视频保持原始宽高比，黑边表示适配窗口；画面右上角可选择流畅（最大 640 宽、15 fps）、均衡（最大 960 宽、30 fps）、清晰（最大 1280 宽、30 fps）或性能（最大 1280 宽、60 fps）。默认清晰，不改变板端编码和录像的 1920×1080；源流低于档位帧率时不会强行补到高帧率。

| 控件 | 实际作用 |
| --- | --- |
| 启动直播 | 启动板端 FFmpeg / VPU 编码与 RTSP 发布 |
| 停止直播 | 正常封口正在进行的录像，再结束此服务的 HDMI 和采集 |
| HDMI 开启/关闭 | 控制板子连接的显示屏，电脑预览可以继续 |
| 重新播放 | 只重建电脑解码器，不重启板端摄像头 |
| 全屏 | 全屏显示实时视频，按 Esc 或“返回控制台”退出 |
| SSH / 视频卡片 | 分别表示控制连接与电脑解码状态，SSH 断开不等于直播结束 |
| VPU / HDMI / 录像卡片 | 以板端实际状态为依据，不根据按钮点击推断成功 |

画面下方还显示电脑解码与显示帧率、预览尺寸、自动重连次数和首帧等待时间。首帧指当前电脑 FFmpeg 启动到完整画面的等待，不是端到端视频延迟。

底部显示帧进度、丢帧、补帧、订阅者数量和更新时间。历史错误记入日志，已经恢复的直播不会仅因旧错误被标成失败。

## 4. 修改编码参数

打开“编码设置”，选择 H.265 或 H.264，填写宽高、帧率、码率、GOP，然后点击“应用参数并重启直播”。

- 默认 H.265、1920×1080、30 fps、2.5 Mbit/s、GOP 30。
- 本板 ISP 尺寸步长为 8，宽高应为 8 的倍数，仍需满足固件与传感器实际支持。
- 码率单位 Mbit/s；2.5 对应板端 2500000 bit/s。GOP 30 在 30 fps 下约每秒一个关键帧。
- 当前传感器实际为 30 fps，界面允许填入 60 fps 预设，但板端在停旧流之前拒绝超过实际采集能力的请求；降低编码帧率采用抽帧，不改变传感器曝光和读出模式。低帧率时可同步降低 GOP。
- “高级：采集节点”默认 `/dev/video44`，不确定节点时保持默认。
- 右侧“运行值”来自板端查询；实际采集尺寸单独确认，不能把填入值当作驱动已经采用。
- 录像时应用按钮被禁用，应先停止录像并等待封口。
- 参数失败时尝试恢复原直播，并报告恢复结果；没有硬编器时明确失败，不切换软件编码。

## 5. 截图、录像与文件

点击底部“截图”，从当前 RTSP 取得 JPEG，自动下载到电脑保存目录，并在“媒体文件”展示最近截图缩略图。

点击“开始录像”，板端创建新的 MP4。直播、HDMI、电脑预览同时继续运行。点击“停止录像”，等待正常封口和 ffprobe 验证；完成后可选中列表中的文件下载，或勾选“停止录像后自动下载”。

媒体列表显示文件名、大小与状态；`partial.mp4` 标为写入中，不作为完成文件下载。下载采用单独 SFTP 连接，进度实时显示，可以取消。取消或失败会清理本次 `.part` 文件，不删除板端录像。

“打开最近下载的文件”会在软件内循环回放 MP4；JPEG 使用电脑默认图片查看器。“打开目录”进入电脑保存位置。下载完成前会比较板端与本地 SHA-256；同名文件也需要内容相同才能复用，内容不同不会覆盖原文件。校验失败清理临时文件，请刷新后重新下载；大文件校验可能需要等待。软件当前不提供自动删除板端录像功能。

板端空间不足 1 GiB 时拒绝新录像；录像中触及阈值时结束录像，直播保留。结束失败的 partial 文件保留在板端供排查。

## 6. 断开、退出与排错

“断开控制与电脑预览”关闭电脑连接，板端任务继续运行。直接关闭软件时会异步释放电脑资源，界面显示退出提示，直到后台结束后自动关闭，不需要再次点击。它不会停止板端直播和录像；需要结束板端任务时先点击“停止录像”或“停止直播”。

| 现象 | 处理 |
| --- | --- |
| SSH 认证失败 | 核对用户名、密码、密钥与私钥口令；确认账号允许 SSH 登录 |
| 主机指纹不匹配 | 核对是否换板、重刷系统或 IP 指向另一台设备，不能直接忽略校验 |
| 摄像头占用 | 停止自己另开的采集程序；软件不会自动杀无关进程 |
| 视频连接失败 / 404 | 查询直播状态；未运行时点击启动，运行中可点击重新播放 |
| 参数失败但原画面恢复 | 查看错误详情，改回设备支持的参数 |
| 下载失败 | 核对网络和保存目录；重新选中已经完成的文件下载 |
| 软件打不开 | 确认整个便携文件夹已完整解压，保留依赖目录 |

打开“运行日志”，可筛选连接、控制、编码、录像、播放和文件事件，并读取板端最近日志。配置、主机指纹与轮转日志在 `%LOCALAPPDATA%\EVM3588CameraConsole\`。日志与下载文件不会自动上传 GitHub。

## 7. 源码运行与打包

本节供继续开发。**电脑 PowerShell，项目根目录**：

```powershell
python -m venv .venv-desktop
```

解释：使用本机 Python 创建独立虚拟环境，不改动已有 Python 包。当前构建使用 Python 3.10.19。

```powershell
.\.venv-desktop\Scripts\python.exe -m pip install -r .\desktop\requirements.lock.txt
```

解释：用虚拟环境的 Python 执行 pip，`-r` 读取固定版本依赖，包括 PySide6、Paramiko、keyring、打包与测试工具。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\run.ps1
```

解释：启动子进程，`-NoProfile` 不加载个人配置，`-ExecutionPolicy Bypass` 为本次进程放行，`-File` 指定启动脚本；它运行源码界面。

```powershell
.\.venv-desktop\Scripts\python.exe -m pytest .\desktop\tests -q
```

解释：运行桌面控制、帧拼接、下载保护、界面结果处理等自动测试；`-q` 输出简洁结果。这组测试不会启停真实开发板。

```powershell
.\.venv-desktop\Scripts\python.exe .\desktop\tests\live_monitor.py --seconds 1800
```

解释：打开真实桌面监测窗口，先在窗口中连接已经运行的直播；出画面后计时 1800 秒，即 30 分钟。期间只查询状态和读取视频，禁用窗口操作，完成后将结果保存到用户目录 `live-acceptance.json`，关闭电脑预览而保留板端直播。

```powershell
.\.venv-desktop\Scripts\python.exe .\desktop\build.py
```

解释：用 PyInstaller 生成免安装目录，复制电脑现有 FFmpeg，附版本与许可记录，再生成 ZIP 与 SHA256。电脑需能从 PATH 找到 `ffmpeg.exe`；需要指定位置时加 `--ffmpeg` 并传入完整路径。构建产物在 `releases/desktop/1.2.0/EVM3588CameraConsole/`，ZIP 在 `releases/`。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools/deploy/deploy.ps1
```

解释：上传板端代码，参数含义同源码启动命令。桌面程序与板端程序分开部署；上传不会自动重启当前直播。更新控制接口后须在板端安排重启，正常使用便携 EXE 不需要每次执行。

## 8. 程序结构与下一步修改

| 模块 | 责任 |
| --- | --- |
| `desktop/main.py` | 应用启动、图标与窗口尺寸 |
| `evm_console/layout.py`、`widgets.py` | 中文界面布局、控件外观和画面绘制 |
| `evm_console/window.py`、`playback.py` | 业务编排、状态与按钮、本地回放窗口 |
| `evm_console/ssh.py` | 主机指纹、SSH 后台队列、JSON 控制、重连 |
| `evm_console/video.py` | FFmpeg 解码、完整帧拼接、最新帧和视频看门狗 |
| `evm_console/files.py` | SFTP 列表、下载、路径检查与取消 |
| `evm_console/core.py` | 连接配置、能力默认值、错误解释与结果校验 |
| `board/ffmpeg_pipeline/avctl.py` | 稳定的板端 CLI 入口 |
| `board/ffmpeg_pipeline/camera_control/` | 配置、通信、生命周期、参数恢复与录像封口 |

新增相机功能时，先在板端实现并验证 JSON 操作，再加入后台调用与 UI 状态，不在按钮回调中直接执行阻塞 SSH。算法处理应使用独立帧消费者；不要让算法耗时堆积预览帧。

本版已实现与实际验收数据见 [Windows 桌面验收记录](../history/Windows_相机控制台验收记录.md)。曝光、增益、ROI、识别算法、音频与多路相机属于后续扩展。原 [FFmpeg 命令行指南](FFmpeg_全链路操作指南.md) 和 [MPP C API 学习指南](路线二_MPP_C_API_操作与修改指南.md) 继续保留。

1.1.0 的改动依据与后续优先级见 [优化调研与实施](../architecture/Windows_控制台优化调研与实施.md)，新测试数据见 [优化验收记录](../history/Windows_控制台优化验收记录.md)。

源码阅读从 [项目程序逻辑与目录导航](../architecture/项目程序逻辑与目录导航.md) 开始。1.2.0 的新模块和实测结果见 [性能指南](4K60与性能监测.md) 与 [验收记录](../history/4K60与性能监测验收.md)。
