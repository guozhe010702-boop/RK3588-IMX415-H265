# FFmpeg + RK3588 VPU：H.265 / RTSP / MP4 全链路操作指南

本指南对应 EVM3588-B、IMX415/con7、Ubuntu 20.04、厂商 5.10.110 内核。摄像头 `/dev/video44` 输出双平面 NV12M；默认 1920×1080、30 fps、H.265 CBR 2.5 Mbit/s、GOP 30，无音频。

## 1. 现在各组件做什么

```text
IMX415 → CSI / ISP → NV12M → 独立 FFmpeg → RK3588 VPU H.265
                                                    ↓
                                             MediaMTX RTSP
                                            ↙      ↓       ↘
                                       HDMI播放  电脑播放  手动MP4录像
```

只有独立 FFmpeg 打开摄像头并编码一次。MediaMTX 负责发布/分发，HDMI 和电脑播放器读取同一条码流。录像进程也是订阅者，它用流复制把已经编码的 H.265 封装成 MP4；不是第二次编码。

| 位置 | 作用 |
| --- | --- |
| `/usr/bin/ffmpeg` | 原系统版本保留，它没有 `hevc_rkmpp` 编码器 |
| `/userdata/av_dev/ffmpeg_pipeline/runtime/bin/ffmpeg` | 新版 FFmpeg，包含 `hevc_rkmpp` 与 `h264_rkmpp` |
| `runtime/lib/` | 新版 MPP/RGA 私有库，只对新 FFmpeg 进程生效 |
| `avctl.py` | JSON 控制接口，供命令行及后续 SSH 上位机共用 |
| `evm-mediamtx.service` | RTSP 服务：8554；管理 API：仅本机 9997 |
| `evm-ffmpeg-control.service` | 管理编码、录像、截图与 HDMI 播放器 |

原 GStreamer 07 脚本和路线二 C 程序仍保留。它们与新链路不能同时打开 `/dev/video44`。默认不自动录像，也没有启用开机自启动。

## 2. 电脑部署与板端构建

电脑终端提示符是 `PS C:\...>`；开发板是 `root@ema:...#`。Windows 路径和 PowerShell 参数不能输入板端 Bash。

电脑 PowerShell：

```powershell
Set-Location -LiteralPath 'C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev'
```

解释：进入电脑上的项目根目录；`-LiteralPath` 按原样处理含中文的路径。其它电脑替换成实际项目目录。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools/deploy/deploy.ps1
```

解释：`powershell.exe` 启动子进程，`-NoProfile` 不加载个人配置，`-ExecutionPolicy Bypass` 对这次运行放行脚本，`-File` 指定部署入口。它上传源码、配置示例、补丁和测试工具，不上传本机缓存或录像，也不自动停止直播、修改板端现有配置或编译 FFmpeg。`-BuildExamples` 仍只编译路线二两个 C 程序。

```powershell
$adbPath = 'C:\Users\dvsense_docker\Desktop\work\RK3588\Tools\platform-tools\adb.exe'
```

解释：在当前电脑终端保存 ADB 路径；新开终端需要重新赋值。

```powershell
& $adbPath shell
```

解释：`&` 执行 ADB，`shell` 进入板端 Bash。接下来构建与控制命令均在板端运行。

```bash
cd /userdata/av_dev/ffmpeg_pipeline
```

解释：进入独立运行环境所在目录。

**当前这块板子已完成构建与安装，正常使用可直接跳到第 3 节。** 新板第一次安装，或按固定源码重建时才需要：

```bash
bash build_runtime.sh --install-build-deps
```

解释：`bash` 执行原生 ARM64 构建脚本；`--install-build-deps` 安装缺少的开发工具/头文件，使用 `--no-upgrade` 保留已安装运行库。随后检出 `versions.json` 中固定的源码提交、应用 NV12M 补丁、以最多 4 个并行任务构建 MPP/RGA/FFmpeg、下载并校验固定版本 MediaMTX。组件安装在独立 `runtime/`，不覆盖系统 FFmpeg 或厂商 MPP/RGA。构建需要网络和一定时间，日志应保留；已经运行的构建会由锁拒绝重复启动。

```bash
bash install_services.sh
```

解释：安装两个 systemd 服务文件、创建数据目录，并在配置不存在时复制配置示例；不会自动启用开机自启动。换安装目录后要重新运行此步骤，因为服务文件中记录了实际绝对路径。

```bash
python3 avctl.py check
```

解释：检查独立 FFmpeg、可用硬编器、VPU 节点、摄像头节点与剩余磁盘空间。`runtimeBuilt=true` 与编码器列表只是环境依据，还应实际编码验证。`check` 不打开摄像头、不启动服务、不改变图像参数。

## 3. 启动直播与两端实时播放

板端 Bash：

```bash
python3 avctl.py start
```

解释：启动必要服务，并按已保存配置让 FFmpeg 直接采集 NV12M，用 `hevc_rkmpp` 调用 VPU 硬编、发布到本机 MediaMTX。缺少硬编器时直接失败，不改用 `libx265`。如果摄像头被其他进程占用，返回具体 PID，不自动终止它们。

```bash
python3 avctl.py preview-start
```

解释：在开发板已有 X11/HDMI 图形会话中启动系统 ffplay，读取 RTSP。它不再打开摄像头；截图、录像或更多电脑客户端可以同时订阅。当前 VPU 编码是硬件路径，播放器解码采用现有播放器能力。

电脑另一个 PowerShell：

```powershell
ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay -framedrop rtsp://192.168.2.221:8554/imx415
```

解释：`ffplay` 播放视频，`-rtsp_transport tcp` 使用 TCP，`-fflags nobuffer` 减少输入缓存，`-flags low_delay` 请求低延迟解码，`-framedrop` 在显示跟不上时丢显示帧。地址为板端 IP、8554 端口和 `/imx415` 路径。不要加 `-f hevc`：RTSP 已提供媒体描述，和旧 TCP 裸码流不同。

加入正在运行的 H.265 流时，首个关键帧之前可能出现参考帧提示；通常等下一个 GOP 即可出画面。若提示一直持续或画面停住，应查询状态和日志。独立 ffplay 不提供完整的自动重连管理，服务中断后必要时重开；后续上位机会管理播放器重启。

```bash
hostname -I
```

解释：在板端查询当前地址；DHCP 变化后，用电脑能到达的 IPv4 替换播放地址。当前示例仅用于局域网。

## 4. 手动 MP4 录像

直播已运行时，在板端执行：

```bash
python3 avctl.py record-start
```

解释：创建唯一文件名，启动第二个 FFmpeg 订阅 RTSP，并用 `-c:v copy` 复制已编码视频、封装 MP4。源编码器不会重新启动。录像位于 `recordings/`，录制中文件名含 `.partial.mp4`，不应把它当作已完成文件。

```bash
python3 avctl.py record-stop
```

解释：发送正常结束信号，等待写入 MP4 索引并用 ffprobe 核对；成功后改为最终 `.mp4` 文件名并返回路径、大小、尺寸和时长。操作同时会报告异常；未正确完成的文件保留为 partial，不会伪装为成功录像。

```bash
python3 avctl.py status
```

解释：返回 JSON 状态。`recording=false` 表示录像已停止；`lastRecording` 保存最后一次完成文件的信息，`capturePid` 不应因为录像启停改变。停止直播也会先结束录像。磁盘不足 1 GiB 时控制器停止录像并保留直播，不自动删除历史文件。

断电或强制杀死正在录制的进程，普通 MP4 可能来不及写完索引；partial 文件会留作排查。本轮采用手动单文件录像，连续分段与断电恢复属于后续扩展。

## 5. 截图与录像下载

板端：

```bash
python3 avctl.py snapshot
```

解释：从同一条 RTSP 解码一帧并生成 JPEG，返回 `snapshots/` 下的唯一文件路径；不再打开摄像头，也不重启直播。JPEG 编码是截图处理，不是视频软件编码回退。

电脑 PowerShell，在项目根目录准备保存目录：

```powershell
New-Item -ItemType Directory -Path .\recordings -Force
```

解释：创建本机录像目录；`-Force` 允许目录已存在，不删除原有内容。

下面是本次实测生成的录像路径。以后把源路径换成 `record-stop` 返回的新路径：

```powershell
& $adbPath pull /userdata/av_dev/ffmpeg_pipeline/recordings/imx415-20261013-094626-a75f35.mp4 .\recordings\
```

解释：`adb pull` 从板子复制到电脑，两个参数分别是板端文件和电脑目录。新开终端时先按第 2 节重新设置 `$adbPath`。传输不会占用摄像头；后续上位机将通过 SFTP 下载。

```powershell
ffplay .\recordings\imx415-20261013-094626-a75f35.mp4
```

解释：打开已完成的本地 MP4，自动读取容器和编码信息。这是文件回放，与 RTSP 直播不同。

## 6. 修改编码配置

配置字段如下；编码格式对应明确的硬件编码器。

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `device` | `/dev/video44` | 当前 IMX415 的采集节点 |
| `codec` | `h265` | `h265 → hevc_rkmpp`，`h264 → h264_rkmpp` |
| `width / height` | `1920 / 1080` | 请求的有效宽高，必须为偶数 |
| `fps` | `30` | 输出帧率配置；不保证驱动改变传感器物理帧率 |
| `bitrate` | `2500000` | 目标 bit/s，即 2.5 Mbit/s |
| `gop` | `30` | GOP 帧数，30 fps 下约一秒 |

输入范围检查不代表硬件支持所有尺寸/帧率；以实际编码、驱动日志和输出为准。范围为宽 96～8192、高 64～8192、fps 1～60、码率 100000～20000000、GOP 1～600。

先结束录像，然后在板端提交完整 JSON：

```bash
printf '%s\n' '{"device":"/dev/video44","codec":"h265","width":1920,"height":1080,"fps":30,"bitrate":4000000,"gop":30}' | python3 avctl.py start --config-stdin
```

解释：`printf` 把配置 JSON 写入标准输出；管道送给 `avctl.py`；`--config-stdin` 从标准输入读取配置。这里将码率改成 4 Mbit/s；原直播通过受控停止/重启应用配置，可能短暂停画面。未知字段、无效类型和越界值会被拒绝；录像中也会拒绝改变直播配置。此功能是重启应用配置，不是无缝运行时调码率。

回到本轮默认配置：

```bash
cat config.example.json | python3 avctl.py start --config-stdin
```

解释：`cat` 读取项目默认配置，通过标准输入提交；随后可按第 3 节打开 HDMI 预览或重开电脑播放器。

## 7. 状态、日志和停止

```bash
python3 avctl.py logs --lines 40
```

解释：返回编码、录像和预览的最近日志；`--lines 40` 限制每类返回 40 行，最大 500 行。不需要手工搜索 PID 或读取整个大日志。

```bash
python3 avctl.py preview-stop
```

解释：只停止此控制器打开的 HDMI 播放器；直播和电脑客户端继续运行。

```bash
python3 avctl.py stop
```

解释：先正常结束录像，再停止此控制器的预览和编码进程，释放摄像头。不会终止其他播放器或无关进程。RTSP 中继服务可以保持运行等待下一次发布。

电脑刷新本地方案页面的状态：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools/deploy/refresh_status.ps1
```

解释：启动只读 ADB 采样脚本；参数含义同部署命令。脚本自动检测新 FFmpeg/RTSP 与原 GStreamer/TCP 链路，输出本机 `board_status.js`；随后刷新方案页面。它不会启动服务或控制摄像头，超过 5 分钟会显示快照过期。

## 8. 源码与兼容补丁为什么必要

- 系统 FFmpeg 虽带 `--enable-rkmpp`，实际编码器列表没有 `hevc_rkmpp`，所以这次构建独立 ffmpeg-rockchip。
- 当前摄像头是 NV12M 两平面，不能把 UV 指针当作 Y 内存后面的连续部分。
- 固定上游提交的多平面拷贝中混用了平面索引与 `data_offset`。补丁按平面选择映射地址，再应用偏移，并逐行去掉 padding。
- 补丁还补齐 NV12M 格式识别、修正 mmap 失败判定与映射数组释放、把不支持 G_PARM 时的帧率分数修正为正确方向。
- 对应头文件及 C 测试保存在 `patches/` 与 `tests/`。测试使用不同 Y/UV 数据、非零偏移和不同 stride，验证输出与已知期望一致，再检查非法长度与尺寸拒绝。
- `avctl.py` 使用 Unix socket 为多次 CLI 请求共享一个控制状态；后台线程读取实际编码进度并监测异常退出。它只管理自己启动的子进程。

## 9. 验收工具与证据

已完成的检查和最终测试数据见 [FFmpeg 全链路验收记录](../history/FFmpeg_全链路验收记录.md)。验证工具不是普通启动命令，`run_acceptance.sh` 会主动中断/恢复直播做 10 次启停与 RTSP 服务重启；使用前应知道画面会短暂中断。

板端单元测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

解释：`-m unittest` 运行 Python 标准测试框架，`discover` 搜索 `tests` 下匹配文件，`-v` 显示各测试结果。它验证配置拒绝、忙摄像头保护、录像时配置保护和截图前置条件，不启停真实摄像头。

板端完整验收：

```bash
bash tests/run_acceptance.sh
```

解释：执行实际硬件验收：测试 NV12M 与控制接口，录制至少一分钟、正常封口，执行 10 次启停、重启 RTSP 服务，再持续监测 30 分钟。它会改变正在运行的直播状态；结果写入 `build/`，失败时尝试恢复此控制器的直播和 HDMI 播放。

电脑连接恢复测试：

```powershell
python .\tools\tests\test_rtsp_client.py
```

解释：电脑 Python 连续连接默认 RTSP 地址 5 次，每次解码一帧并测量耗时。这个值是连接到可解码帧的时间，不是摄像头到屏幕的真实延迟。

## 10. 常见问题与恢复

| 现象 | 原因与处理 |
| --- | --- |
| `Camera busy` | 其他程序占用采集节点；先核对其身份，只在原终端停止自己的管线 |
| `Required hardware encoder unavailable` | 独立运行环境尚未构建成功；查询 `check`、构建日志与版本锁，不回退软件编码 |
| `Stream is not ready` | 直播尚未出帧、服务未就绪或编码已经退出；查看 `status` 和 `logs` |
| 电脑有首帧参考帧提示 | 中途加入等待下一个关键帧；持续报错时检查流和 GOP |
| HDMI 失败 | 必须有已登录的 X11 图形会话；当前已验证 `:0`，不要照搬到其它固件会话 |
| 录像文件仍是 partial | 未正确封口，查录像日志；不要简单改名当作成功文件 |
| 旧 5000 无监听 | 当前使用新 RTSP 8554，是预期的链路变化 |
| 重新启动板子后没有画面 | 默认没有开启自动启动，按第 3 节手动启动 |

回到原 GStreamer 方案时，先执行第 7 节的 `avctl.py stop` 释放摄像头，再在板端执行：

```bash
DISPLAY=:0 bash /userdata/av_dev/07_h265_preview_tcp.sh
```

解释：`DISPLAY=:0` 选择图形会话，`bash` 执行保留的 07 脚本。这会回到旧的 HDMI + TCP 5000 裸 H.265 方式。原录像和配置不会被删除。

## 11. 版本、备份与后续开发

构建源码提交和 MediaMTX SHA-256 在 `versions.json`；实际二进制和补丁校验值由构建脚本保存到板端 `runtime/build-manifest.json`。本次实施前已有本地备份及 Git 标签 `before-ffmpeg-fullchain-20261013`。

代码、补丁、配置示例、操作说明和验收工具上传 GitHub；真实录像、截图、设备快照、凭据、缓存和运行组件保留在本地。重新打包不会把这些运行数据混入 ZIP。

Windows 上位机已实现，中文界面封装相同的 SSH 控制入口。使用见 [桌面操作指南](Windows_相机控制台操作指南.md)，架构参考见 [上位机设计与开源调研](../architecture/Windows_上位机设计与开源调研.md)。
