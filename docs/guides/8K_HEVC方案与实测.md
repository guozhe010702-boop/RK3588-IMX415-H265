# IMX415 实拍：RK3588 8K30 硬编与 8K60 硬解

本功能属于 `av_dev` 视频工程，不是 YOLO 检测工程；不新增网页。本次主验证全部使用 **IMX415 实拍图像**，不调用彩条、`testsrc` 或其它合成源。

## 1. 能力与实际链路

RK3588 的规格是 **最高 8K30 H.264/H.265 编码、8K60 解码**，二者不同。[瑞芯微官方规格](https://www.rock-chips.com/a/en/products/RK35_Series/2022/0926/1660.html)

IMX415 推荐记录尺寸为 **3840×2160**，有效像素约 846 万；它不能提供 7680×4320 的原生空间细节。[Sony 官方资料](https://www.sony-semicon.com/files/62/pdf/p-12_IMX415-AAQR_AAMR_Flyer.pdf)

因此当前设备采用以下两条实拍路线，均为 UHD 8-bit 4:2:0 HEVC：

```text
A. 实时 8K30 硬编
IMX415 → /dev/video44 NV12M 3840×2160 / 60 fps
       → 跳过开头 5 帧 → 每 2 帧选 1 帧（30 fps，不补帧）
       → RGA 放大到 7680×4320 → hevc_rkmpp / VPU
       ├─ MP4
       └─ MediaMTX :8555/imx415-upscaled-8k30 → 电脑 ffplay

B. 实拍来源 8K60 硬解
IMX415 真实 4K60 → 板端 4K60 HEVC 录像
       → 电脑离线逐帧放大到 8K，libx265 编码，保持原有 60 fps 时间戳
       → 上传 8K60 文件及来源清单
       → 板端 hevc_rkmpp 硬解 → 可选 RGA 缩至 1080p
```

A 是实时相机画面，但 **4K 放大不是原生 8K 拍摄**。B 的每帧同样来自相机；电脑离线编码不是 RK3588 8K60 编码，也不是实时 8K60 上行直播。本轮没有插帧、重复帧或把 30 fps 文件改标为 60 fps。当前屏幕最高报告 1080p，不能称为原生 8K 显示。

## 2. 哪些程序是新做的

以下路径均相对于 `av_dev/`，只有这一份源码作为本项目维护入口。

| 新增文件 | 作用与执行位置 |
|---|---|
| `board/ffmpeg_pipeline/tests/imx415_8k.py` | **本轮实拍主程序，板端 Python**。`encode30` 负责采集、RGA 放大、VPU 编码、MP4/可选 RTSP；`capture60` 录制真实 4K60；`decode60` 核验来源清单及 SHA-256 后做 VPU 硬解测试 |
| `board/ffmpeg_pipeline/tests/codec_metrics.py` | 共用进程、单调时间帧率、MPP 设备访问、错误检测和摄像头占用检查；**不生成任何图像** |
| `tools/tests/run_imx415_8k.py` | **电脑端一键入口**。通过现有 ADB 上传必要脚本，启动板端任务、可选打开 ffplay，等待退出，下载录像和实测证据 |
| `tools/tests/prepare_camera_8k60.py` | 电脑离线准备实拍来源的 8K60 文件；只接受真实 4K60 验证结果，校验原录像哈希、帧率和时间戳；转换后再次核对帧数及 PTS |
| `board/ffmpeg_pipeline/profiles/8k/mediamtx.yml` | 独立 8555 端口配置；实拍路径为 `imx415-upscaled-8k30`，仅本机允许发布，局域网可读取；不占原 8554 端口 |
| `board/ffmpeg_pipeline/tests/test_imx415_8k.py` | 新实拍路线的自动测试：采集源、真实选帧、禁止低帧率冒充 60 fps、转换参数及来源拒绝 |
| `board/ffmpeg_pipeline/tests/hdmi_8k.py` | 给已运行的实拍 8K30 直播增加板端 VPU 硬解→RGA→HDMI 支路；不打开摄像头，保存每秒性能 CSV 和状态 |
| `tools/tests/hdmi_imx415_8k.py` | 电脑通过 ADB 单独启动、查询、停止 HDMI 支路，下载其日志与 CSV；不重启编码器 |
| `board/ffmpeg_pipeline/tests/test_hdmi_8k.py` | 验证完整 8K 硬解、先 RGA 缩放再下载、带时间戳管道、输入尺寸报告与原控制接口兼容 |
| `board/ffmpeg_pipeline/tests/codec_8k.py` | **上一轮**合成素材的独立 VPU 基准入口；本轮实拍入口不调用它 |
| `tools/tests/prepare_8k_fixtures.py` | **上一轮**生成带标识的合成测试素材；不是相机程序，本轮不运行 |
| `tools/tests/run_8k_lab.py` | **上一轮**合成素材上传及测试编排；保留作历史诊断，不作为实拍验收 |
| `board/ffmpeg_pipeline/tests/test_codec_8k.py` | 上一轮基准的参数、计数和错误检查测试 |

修改的原程序：`camera_control/config.py` 报告 SoC 规格并拒绝 8K60 编码；`support.py` 读取实际传感器名称；`controller.py` 在停止原直播之前拒绝 IMX415 的伪原生 8K 采集请求。相应回归位于 `tests/test_control.py`。

**桌面软件尚未新增 8K 实验按钮。** 普通桌面继续使用实际相机尺寸和原控制接口；本轮实验用独立命令，不能直接在桌面把采集尺寸填成 7680×4320。YOLO 的九线程推理、NPU 统计与本次 VPU 编解码程序分开。

## 3. Windows 一键看实拍 8K30

前提：开发板通电、IMX415/con7 接好、USB-C 数据线与有线网连接；电脑已有 Python、ffplay，私有 FFmpeg 已部署到板端 `/userdata/av_dev/ffmpeg_pipeline/`。ADB 使用工程相邻 `Tools/RKDevTool_296/.../bin/adb.exe`，不要另开不同版本的 ADB server。

**执行位置：Windows PowerShell，`C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev`。**

当前电脑已验证 Intel UHD Graphics 770。日常看实时画面，使用下面的持续预览：

```powershell
python .\tools\tests\run_imx415_8k.py --mode encode30 --rtsp --preview --live --handover --preview-backend intel-qsv
```

解释：`--live` 保持窗口和 RTSP 运行，直到关闭窗口或按 Esc/Q，不再按 30 秒或帧数自动退出，**此模式不写 MP4**；`--preview-backend intel-qsv` 使用电脑 FFmpeg 的 `hevc_qsv` 完整解码 8K，通过 `vpp_qsv` 在 GPU 上缩到 1280×720，下载缩小后的 NV12，经带时间戳 NUT 管道交给 ffplay。局域网中仍传 8K30 H.265，板端仍执行 VPU 8K30 硬编。硬件初始化失败会明确报错，不静默改用软件解码。该选项要求兼容 Intel 核显、驱动，以及含 `hevc_qsv`/`vpp_qsv` 的电脑 FFmpeg。

窗口关闭后，仅结束本次实验，再恢复实验前的已知直播/HDMI 状态；实验前服务停着则保持停止。不要同时启动第二条相机测试。日志在本次 `.cache/imx415-8k/<时间>-encode30/`：`preview-probe.log`、`preview-stream.json` 检查可读性和尺寸；`preview-decoder.log`、`preview-progress.txt` 记录核显解码；`ffplay.log` 记录播放器错误与丢帧；`player.json` 保存本次进程标识。日志和实拍图像不上传 GitHub。

原来 `--frames 900` 的窗口约 30 秒后关闭是限时测试行为，不能把它当成持续预览。原软件解码路径在这台电脑上曾出现大量显示丢帧、缓存持续增长；现在播放器使用 `-noinfbuf` 限制缓存，Intel QSV 路径先在 GPU 缩小再下载，避免持续拷贝完整 8K 帧。另一台电脑没有兼容 Intel GPU 时可使用默认 `software` 路径，但必须实测能否跟上 30 fps，不能承诺同等性能。[FFplay 缓冲及播放选项](https://ffmpeg.org/ffplay.html)

需要**有界编码测试并保存 MP4**时，仍使用：

```powershell
python .\tools\tests\run_imx415_8k.py --mode encode30 --frames 3600 --rtsp --preview --handover
```

解释：`--mode encode30` 使用真实相机和 RGA/VPU 8K30 路线；`--frames 3600` 输出约 120 秒，属于有界实验；`--rtsp` 同时写 MP4 并启动独立 RTSP 服务；`--preview` 在电脑打开 ffplay，完整解码后缩至 1280 宽；`--handover` 允许通过原控制接口临时停止已有直播，并在结束后恢复原配置及原 HDMI 状态。遇到未知摄像头占用者会报错，不自动杀进程；正在录像时拒绝切换。

原直播未运行时，测试结束保持停止状态。这个命令不启用开机启动，也不修改内核、厂商库或 ISP 服务。录像和日志留在本机 `.cache/imx415-8k/<时间>-encode30/`，板端副本在 `lab8k-camera/`；每次新建目录，不覆盖旧证据。

如果不使用自动预览，在同一次实验尚未结束时，可在 **另一个 Windows PowerShell、任意目录** 执行：

```powershell
ffplay -rtsp_transport tcp -framedrop -vf scale=1280:-2 rtsp://192.168.2.221:8555/imx415-upscaled-8k30
```

解释：TCP 接收板端实拍 RTSP；`-vf scale=1280:-2` 在完整 8K 解码后等比例缩小显示，`-2` 保持偶数高度；`-framedrop` 允许播放器跟不上时丢弃旧显示帧。网络中仍是 8K30 压缩流；显示窗口缩小不代表只解码了 720p。实验结束时 RTSP 自动关闭，断流属于正常结束。

## 4. 在板端 Linux 直接运行

先通过上述 Windows 入口完成脚本上传。以下命令在 **开发板 Linux 终端** 执行，不能粘贴到 Windows PowerShell。

```bash
cd /userdata/av_dev/ffmpeg_pipeline
```

解释：进入板端实际运行目录；Windows 的 `C:\Users\...` 路径在板端不存在。

```bash
python3 tests/imx415_8k.py --mode encode30 --frames 3600 --rtsp --handover --output "lab8k-camera/live-$(date +%Y%m%d-%H%M%S)"
```

解释：运行实拍 8K30、约 120 秒、MP4＋RTSP 的同一流程。`--output` 指定证据目录；`date` 加入当前时间防止覆盖旧记录；`--handover` 的保护与恢复行为同前。私有库搜索路径由脚本仅对子进程设置，不需要改系统 `LD_LIBRARY_PATH`。

结束后 `result.json` 包括实际尺寸、传感器报告帧率、采集/输出速率、采集缺口、VPU 设备访问、补帧计数及封装校验；`command.json` 为实际 FFmpeg 命令，`ffmpeg.log` 和 `progress.jsonl` 保留原始证据。Ctrl+C 会清理本次子进程并尝试恢复原直播；强制断电不保证 MP4 封口。板端也支持在上述命令中增加 `--live` 持续推流，不录像，此时通过 Ctrl+C 停止。

## 5. 准备和验证实拍来源 8K60 硬解

以下全部在 **Windows PowerShell，av_dev 根目录** 执行，依次完成。

```powershell
python .\tools\tests\run_imx415_8k.py --mode capture60 --frames 600 --handover
```

解释：录制 600 个真实 4K60 相机帧，约 10 秒；没有先放大，也没有补帧。传感器实际报告不足 60 fps 时明确失败，不继续伪造 60 fps 素材。测得采集或编码不足 59 fps 时，后面的素材准备程序也会拒绝。

```powershell
$cameraRun = Get-ChildItem .\.cache\imx415-8k -Directory -Filter '*-capture60' | Sort-Object Name -Descending | Select-Object -First 1
$cameraEvidence = Join-Path $cameraRun.FullName ($cameraRun.Name + '\evidence')
$prepared8k = '.\.cache\imx415-8k\offline-' + (Get-Date -Format yyyyMMdd-HHmmss)
```

解释：第一行定位最近一次真实采集目录；第二行定位下载的录像和板端证据；第三行为离线转换创建新的输出路径。这些变量只用于本次 PowerShell 会话，不改系统变量。

```powershell
python .\tools\tests\prepare_camera_8k60.py --input "$cameraEvidence\camera-4k60.mp4" --evidence "$cameraEvidence\result.json" --output $prepared8k --frames 120
```

解释：从已验证的真实 4K60 录像选前 120 帧，仅做空间放大和电脑 `libx265` 离线编码，得到 2 秒的 8K60 文件；逐包核对时间戳没有改变，并生成 `camera-source.json`。FFmpeg/ffprobe 需在电脑 PATH 中；转换速度可能远低于实时，不计入板端硬编性能。原录像、转换文件及清单只保留本地。

```powershell
python .\tools\tests\run_imx415_8k.py --mode decode60 --input "$prepared8k\camera-upscaled-8k60.mp4" --manifest "$prepared8k\camera-source.json" --frames 1200 --handover
```

解释：上传实拍来源文件，核验 SHA-256、HEVC、真实 8K 尺寸与 60 fps，然后以 `hevc_rkmpp` 硬解。`--frames 1200` 循环读取该素材进行足够长的不限速吞吐测试；这是**文件回放**，不把循环当作持续拍到了 1200 个新场景帧，也不拿吞吐值冒充屏幕帧率。

```powershell
python .\tools\tests\run_imx415_8k.py --mode decode60 --input "$prepared8k\camera-upscaled-8k60.mp4" --manifest "$prepared8k\camera-source.json" --frames 1200 --display-scale --handover
```

解释：在完整 8K 硬解后增加 RGA 缩至 1920×1080、下载 NV12 帧，验证显示前的数据处理吞吐。此命令输出到空接收端，**不会自动打开 HDMI 窗口**；不能据此宣称已经验证物理显示帧率。

## 6. 实现细节与统计边界

- 相机始终只由一个 FFmpeg 进程打开。当前 NV12M 双平面采集沿用已有兼容补丁、stride 拷贝和 16 个 mmap 缓冲，NPU 不参与这一视频实验。
- 启动跳过 5 帧；60→30 使用真实选帧。厂商重启时可能返回旧时间戳，因此对选出的真实帧重新建立连续 PTS，同时独立统计实际采集和编码的单调时间差。
- `select` 保留输入声明的帧率，故再用 `fps` 滤镜整理已经均匀的 30 fps 时间戳，让 HEVC VUI/RTSP 正确声明 30；详查滤镜日志的 duplicated 计数，实测为 0。它不把低帧率相机补成 60 fps。
- 输出仍为 CBR 目标 60 Mbit/s、GOP 30、无 B 帧、无音频；MP4 与 RTSP 共用一次编码。目标码率不是实测网口流量，也不保证任意场景画质。
- 稳定帧率为计数增量除以单调时间增量；另保留包含初始化开销的全程平均。采集缺口保留启动原始计数，并单列稳定采样区间的新增值，不把两者混淆。
- `--handover` 只管理原控制接口确认的直播；不杀其它进程。不支持录像中切换。正常/失败退出都进入清理与恢复；开始前原服务停着，结束仍停着。
- `.cache/` 中的实拍画面、录像、日志、状态和路径清单不上传 GitHub。GitHub 提供程序、配置、说明与无图像的实测数字。

## 7. 2026-10-21 实拍验证记录

设备：当前 EVM3588、IMX415/con7、`/dev/video44`，传感器报告 60 fps；内核 `5.10.110`。私有 FFmpeg 使用 `hevc_rkmpp` 和 `scale_rkrga`，不改内核或系统库。下表是短测，不是 30 分钟验收。

| 测试 | 实测结果 | 说明 |
|---|---|---|
| 实拍 RGA→8K30/VPU/MP4/RTSP，第一轮 | 900 帧；稳定编码 30.00 fps，采集 60.00 fps | 约 30 秒；启动时存在旧帧序号跳变；稳定区间新增缺口 0 |
| 修正码流帧率声明后复测 | 600 帧；稳定编码 29.95 fps，采集 59.99 fps | MP4 7680×4320/30 fps/20 秒；滤镜 duplicated=0，编码 dup/drop=0 |
| 电脑 RTSP 读取 | HEVC、7680×4320、30/1；读取 30 个视频包 | MediaMTX 同时记录电脑订阅成功；原相机画面由 FFmpeg 编码，不是测试图 |
| 真实 4K60 素材采集 | 600 帧，10 秒；采集 60.02 fps、编码 60.05 fps | 稳定区间新增缺口 0；无编码补帧 |
| 电脑离线转实拍来源 8K60 | 120 帧，2 秒，原 PTS/帧数保持 | `libx265` 约 4.52 fps，仅是离线素材准备 |
| VPU 硬解实拍来源 8K60 | 1200 帧，稳定吞吐 109.05 fps | 不限速循环文件，约 10 秒统计窗；全程含初始化 108.75 fps |
| VPU 硬解＋RGA 1080p＋下载 | 1200 帧，稳定吞吐 76.88 fps | 约 14.7 秒统计窗；全程含初始化 76.47 fps；未测物理屏幕帧率 |
| 共用测量模块整理后回归 | 8K30 600 帧约 29.92 fps；8K60 硬解＋RGA 1200 帧约 75.62 fps | 无编码补帧、无滤镜重复帧、无帧错误；稳定采集约 59.98 fps，区间新增缺口 0 |
| 持续预览停止/恢复检查 | 约 10 秒、298 帧；停止请求后编码器和服务退出，原停止状态保持 | 未创建 MP4；正常停止由 `livePreviewEnded` 单独标记，不冒充有界验收通过 |
| 软件预览故障复现 | 板端约 350 秒保持 30.00 fps、采集约 59.99 fps、稳定段缺口 0；电脑软件播放掉帧并积压缓存 | 不是相机降帧；修复为有界缓冲和显式 Intel QSV 预览后重新验证 |
| Intel QSV 初步验证 | 本机 8K 文件硬解＋GPU 缩放 120 帧约 1.12 秒；实时输出约 30 fps | 播放器短测丢帧 0、队列接近 0；只作当前电脑短测，待现场确认与长测 |

持续预览约 140 秒时，QSV 进度为 4199 帧、全程平均 29.96 fps，编码补帧/丢帧均为 0；播放器累计丢弃 16 个显示帧，视频队列仍接近 0，没有此前持续积压的现象。初期显示丢帧为 0 不代表永远零丢帧。FFplay 的 `M-V` 是播放时钟差，不能当作镜头到屏幕的精确延迟。本机直接 Vulkan 播放曾异常退出，故当前使用显式 QSV 硬解/GPU 缩放＋SDL 显示小帧的路径，没有升级驱动或替换原桌面播放器。

上述编解码均观察到 MPP 设备访问，帧错误扫描为空；结束后无本次 FFmpeg/MediaMTX 残留。开始时原控制服务未运行，结束仍保持停止。已抽取录像帧确认是摄像头实拍室内画面；电脑实时窗口的可见流畅程度仍以现场观察为准。本次场景主要静止，尚未做高复杂运动验收。启动缺口不能因此宣称已根治；相机源放大也不增加原生细节。

原始证据位于本机 `.cache/imx415-8k/20261021T021555Z-encode30/`、`20261021T022138Z-encode30/`、`20261021T021715Z-capture60/`、`20261021T021857Z-decode60/`、`20261021T021920Z-decode60/`。8K30 复测 MP4 SHA-256：`130eff5bda20f1dc937b61430db8b99a1ae731cc2eedd18fed2155c42025e56f`；实拍来源 8K60 文件 SHA-256：`3c57cf1df8e1cf880d6d397da8fce770791fe85078fded7d3edf11a12ceb0203`。

上一轮合成基准保留原 `SYNTHETIC_CODEC_ONLY` 标签，历史实测为编码约 34 fps、解码约 109 fps，不用于本轮实拍验收。新的默认说明与操作均走上述相机路线。

## 8. 尚未完成的验收

当前完成的是有界实验脚本和实拍短测，尚未完成原生 8K 传感器接入、外部实时 8K60 编码器、8K 屏幕显示、8K 桌面按钮及连续 30 分钟高复杂运动场景测试。电脑可见预览的长期帧率、网口实际带宽、温度和资源趋势也需要独立长测，不能由文件元数据或 SoC 规格推断。

若需要原生 8K 实拍，应另选传感器/ISP/采集路径；若需要实时 8K60 网络输入，应另备支持该编码能力的外部设备。当前方案让现有 IMX415 提供真实画面，清楚保留空间放大和离线步骤的边界。

## 9. 实拍 8K30 硬编＋板端硬解 HDMI

这条支路已接到当前实拍直播，不再读取 `/dev/video44`。完整流程为：

```text
IMX415 4K60 实拍 → 选取 30 fps → RGA 放大 8K → VPU hevc_rkmpp 编码
  → MediaMTX :8555/imx415-upscaled-8k30
      ├→ 板端 hevc_rkmpp 完整硬解 7680×4320
      │   → RGA 缩至 1920×1080 → NUT/NV12 时间戳管道 → 系统 ffplay → HDMI
      └→ 电脑原有 Intel QSV 预览（可同时运行）
```

当前 HDMI-1 的实际模式为 **1920×1080、60 Hz**；视频编码与解码目标都是 **30 fps**。显示器刷新率、编码帧率、解码输出帧率与实际显示帧率分别统计，不把 1080p 屏幕描述成原生 8K 屏幕。屏幕全屏显示只改变窗口，不改 EDID 或系统显示模式。

复用的 `camera_control/decoder.py` 新增可选源地址和带时间戳 NUT 管道；原控制器默认仍读取 8554 的 `imx415` 路径，原裸流调用保持兼容。实验读取 8555 的实拍 8K30，明确使用 `hevc_rkmpp`，硬解失败不改成软件解码。RGA 缩放发生在完整 8K 解码之后。

以下命令均在 **Windows PowerShell、av_dev 根目录**执行；先保持现有实拍 8K30 源运行。

```powershell
python .\tools\tests\hdmi_imx415_8k.py start
```

解释：上传所需 HDMI 程序、备份原解码模块，附加板端硬解显示支路；已有该支路时直接报告现状，不重复启动。摄像头采集和编码器不重启。源未运行、尺寸不符、HDMI 未连接时明确报错。

```powershell
python .\tools\tests\hdmi_imx415_8k.py status
```

解释：查询支路是否存活及数据是否过期；`metrics.display.inputSize` 是完整硬解尺寸，`displaySize` 是缩放尺寸，`intervalFps` 是计数与单调时间差得到的解码输出速率；`encoderVpuOpen`、`display.vpuDeviceOpen` 分别观察两个进程是否打开 MPP 设备。`processes` 的 CPU 百分比按单个逻辑核为 100%，不能直接当作整板 CPU 百分比；RSS 是各进程驻留内存，`memory.percent` 是板端整体内存使用率。

```powershell
python .\tools\tests\hdmi_imx415_8k.py collect
```

解释：把本次状态、原始日志、命令和 `metrics.csv` 下载到电脑 `.cache/hdmi-8k/`，不停止直播。CSV 每秒一行，包括编码/解码计数与速率、三个进程的 CPU/RSS、整体内存占用和温度；文件保留本地，不上传 GitHub。`logs/preview.log` 的 `fd` 是播放器丢显示帧计数，不等于编码丢帧。

```powershell
python .\tools\tests\hdmi_imx415_8k.py stop
```

解释：仅停止 HDMI 读取和显示支路，保持采集、硬编码、RTSP 以及电脑预览运行。再次执行 `start` 可重新接入。直接在 HDMI 窗口按 Esc/Q，也会结束本次 HDMI 支路。

当前实拍源由电脑的 `run_imx415_8k.py --live` 测试管理，关闭它的电脑预览窗口会结束该源，HDMI 会随源结束清理。若需要完全独立于电脑运行，先停止现有源，再按第 4 节在板端启动带 `--live` 的源；然后在另一个**板端 Linux 终端、`/userdata/av_dev/ffmpeg_pipeline` 目录**执行：

```bash
python3 tests/hdmi_8k.py --output "lab8k-camera/hdmi-$(date +%Y%m%d-%H%M%S)"
```

解释：只接入已有的实拍 8K30 源，持续硬解到 HDMI；`--output` 保存本次证据，时间后缀避免覆盖旧数据。Ctrl+C 只结束此 HDMI 支路。无需电脑解码才能在板端屏幕显示。

2026-10-21 本轮首次并行观察超过 5 分钟：稳定统计区间约 318 秒，编码约 **29.91 fps**、板端解码输出约 **29.73 fps**；两进程全程观察到 MPP 设备访问，解码错误记录为空，最高温度约 **55.5°C**，板端整体内存约 **48.3%**。完整输入为 7680×4320，HDMI 输出为 1920×1080。电脑核显预览同时保留。

这是功能导通与短测，**不是零丢帧或 30 分钟稳定性验收**。HDMI 播放器在约 381 秒时累计丢弃约 1739 个显示帧，输入视频队列约 3～9 MiB；解码输出接近 30 fps不代表屏幕逐帧显示了 30 fps。保留这些数据，后续可针对显示端优化。`M-V` 只是播放器时钟差，不是精确镜头到屏幕延迟；本次也没有消除已有相机源的全部序号缺口。
