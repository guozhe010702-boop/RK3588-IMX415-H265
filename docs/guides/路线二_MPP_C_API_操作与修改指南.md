# 路线二：IMX415 → V4L2 → MPP C API → H.265

本文对应当前 EVM3588-B：IMX415 接 con7，采集节点 `/dev/video44`，电脑与板子通过局域网通信，板子连接 HDMI 显示器。板子此前的 IP 是 `192.168.2.221`，实际地址以板端查询为准。

## 1. 先理解现在运行的是什么

2026-10-13 已切换到 **FFmpeg + RK3588 VPU + MediaMTX RTSP**，HDMI 与电脑读取同一直播流。操作见 [FFmpeg 全链路指南](FFmpeg_全链路操作指南.md)。原 07 GStreamer/TCP 5000 脚本保留为备用。路线二的 C 程序已经部署并测试，但它是按指定帧数录制 H.265 文件的学习程序，录完自动退出。

| 程序 | 输入与输出 | 现在可以做什么 |
| --- | --- | --- |
| `07_h265_preview_tcp.sh` | 摄像头 → HDMI + H.265 TCP 5000 | 同时看两端实时画面 |
| `yuv_mpp_enc` | 连续 NV12 文件 → H.265 文件 | 不打开摄像头，单独学习和验证 MPP |
| `v4l2_mpp_enc` | `/dev/video44` 双平面 NV12M → H.265 文件 | 学习真实取帧、内存布局、逐帧硬编 |

**摄像头 C 程序与 FFmpeg 或 07 不能同时采集 `/dev/video44`。** 先做不占摄像头的文件测试，准备好后暂停当前直播，完成摄像头测试，再恢复直播。编译、阅读源码和文件测试都不需要停当前画面。

2026-10-12 已验证：两个程序在板端编译成功；离线测试生成完整 30 帧 640×360 HEVC；IMX415 生成完整 60 帧 1920×1080 HEVC，耗时约 1.96 秒。`ffprobe -count_frames` 验证了帧数。短测试不等于长时间稳定性验证。

## 2. 文件怎么对应

电脑端以项目根目录的 `examples/mpp_c_api/` 为源码入口；不再维护第二份解压源码目录。部署脚本把 C 源码传到板端独立目录 `/userdata/av_dev/mpp_route2/`。

| 文件 | 责任 | 建议阅读顺序 |
| --- | --- | --- |
| `yuv_mpp_enc.c` | 解析参数、读原始帧、调用共用编码器 | 1：先看清一帧从哪里来 |
| `mpp_h265.h` | `H265Encoder` 状态结构和三个接口 | 2：认识对象与资源 |
| `mpp_h265.c` | 初始化 MPP、设置配置、送帧、取包、写码流、释放资源 | 3：编码核心 |
| `v4l2_mpp_enc.c` | V4L2 两平面 MMAP、出队/入队、摄像头循环 | 4：接上真实摄像头 |
| `Makefile` | 编译两个入口和共用引擎，链接 `librockchip_mpp` | 5：看如何构建 |

这里调用的是 RK3588 的硬件编码器。C 程序负责采集、配置与内存管理；H.265 的预测、变换、量化等压缩工作由硬件完成。阅读调用链能理解输入、参数与输出的关系，但不能把 API 层源码视为 H.265 算法本身的实现。

## 3. 电脑与板端终端一定要分清

- `PS C:\...>` 是电脑 PowerShell：运行部署、ADB、拷文件和电脑 ffplay。
- `root@ema:...#` 是开发板 Bash：运行 make、GStreamer、C 程序和板端 ffprobe。
- Windows 的 `C:\...` 目录在板子上不存在；`DISPLAY=:0` 是 Bash 的环境变量赋值语法。

### 3.1 电脑 PowerShell：部署并编译

先进入项目根目录：

```powershell
Set-Location -LiteralPath 'C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev'
```

解释：`Set-Location` 切换电脑当前目录；`-LiteralPath` 按原样使用含中文的路径。换电脑后替换这段绝对路径。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools/deploy/deploy.ps1 -BuildExamples
```

解释：`powershell.exe` 启动子进程；`-NoProfile` 避免个人配置干扰；`-ExecutionPolicy Bypass` 对这次进程放行脚本；`-File` 指定部署脚本；`-BuildExamples` 要求上传后在板端执行 make。脚本检查恰好一台 ADB 设备，逐个上传文件并检查返回值。它不停止正在运行的 07 管线。

设定本机 ADB 路径：

```powershell
$adbPath = 'C:\Users\dvsense_docker\Desktop\work\RK3588\Tools\platform-tools\adb.exe'
```

解释：保存 `adb.exe` 的路径供下面使用；赋值本身不连接或修改板子。

```powershell
& $adbPath devices
```

解释：PowerShell 的 `&` 执行变量所指的程序；`devices` 列出 ADB 设备。应看到序列号和 `device`。没有设备时先处理 USB 数据线或驱动。

```powershell
& $adbPath shell
```

解释：进入板端 Bash。出现 `root@ema` 提示符后，下面的 Linux 命令才可以执行。

### 3.2 板端 Bash：检查构建

```bash
cd /userdata/av_dev/mpp_route2
```

解释：进入已部署的路线二源码与二进制目录。

```bash
make
```

解释：按照 Makefile 编译修改过的源文件；把 `mpp_h265.o` 分别与两个入口链接，生成 `yuv_mpp_enc` 和 `v4l2_mpp_enc`。当前板子已安装匹配的 MPP 开发文件，无需为了这次操作重装库。

```bash
ls -l yuv_mpp_enc v4l2_mpp_enc
```

解释：查看两个可执行文件的存在、权限、大小与更新时间。仅文件存在不能证明编码正确，下一步还要验证输出。

## 4. 第一轮：文件编码，保持两端实时画面

仍在板端 `/userdata/av_dev/mpp_route2/` 中。

```bash
gst-launch-1.0 -q videotestsrc pattern=smpte num-buffers=30 \
  ! video/x-raw,format=NV12,width=640,height=360,framerate=30/1 \
  ! filesink location=learn_640x360.nv12
```

解释：`gst-launch-1.0` 创建生成文件的管线；`-q` 减少日志；`videotestsrc` 生成彩条而不是读取摄像头；`num-buffers=30` 生成 30 帧；中间 caps 规定 NV12、640×360、30 fps；`filesink` 把未压缩数据写入文件；每行末尾 `\` 表示同一命令续行。输入文件大小应为 `640×360×1.5×30 = 10368000` 字节。复测时换新文件名，避免覆盖需要保留的原始帧。

```bash
./yuv_mpp_enc -i learn_640x360.nv12 -o learn_640x360.h265 \
  -c h265 -w 640 -h 360 -b 1000000 -f 30 -n 30
```

解释：`./` 表示当前目录的程序；`-i` 是输入文件；`-o` 是输出码流；`-c h265` 指定 H.265；`-w/-h` 是宽高；`-b 1000000` 是目标 1 Mbit/s；`-f 30` 配置编码帧率；`-n 30` 编码 30 帧。输入必须是无行尾填充、连续排列的 NV12；输出通过独占创建打开，已有同名文件会被拒绝，复测改输出名称即可。

```bash
ffprobe -v error -f hevc -count_frames \
  -show_entries stream=codec_name,width,height,nb_read_frames \
  -of default=noprint_wrappers=1 learn_640x360.h265
```

解释：`ffprobe` 检查输出；`-v error` 仅打印错误；`-f hevc` 指定裸 H.265 格式；`-count_frames` 实际读取/解码统计；`-show_entries` 只保留所需字段；`-of` 设置简洁显示。预期 `codec_name=hevc`、`width=640`、`height=360`、`nb_read_frames=30`。若只检查文件非空，无法发现丢帧或不能解码。

## 5. 第二轮：暂停预览，测试 IMX415，再恢复

### 5.1 板端暂停当前 FFmpeg 直播

开发板 Bash：

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py stop
```

解释：`python3` 执行统一入口，`stop` 先正常结束录像，再停止本服务的 HDMI 播放和 FFmpeg 采集，释放摄像头。不会终止其它应用。此时两端画面短暂中断。

```bash
lsof /dev/video44
```

解释：`lsof` 检查摄像头仍被哪些进程打开。没有进程行时再运行 C 程序；如果有无关应用占用，先核对其身份。不要直接批量杀进程。旧 07 的停止方法见 FFmpeg 指南中的恢复说明。

### 5.2 板端运行摄像头 C 程序

```bash
./v4l2_mpp_enc -d /dev/video44 -o learn_imx415.h265 \
  -c h265 -w 1920 -h 1080 -b 4000000 -f 30 -n 60
```

解释：`-d` 指定采集节点；`-o` 指定新的裸码流文件；`-c` 指定 H.265；`-w/-h` 请求 1920×1080；`-b` 设置目标 4 Mbit/s；`-f` 配置 30 fps；`-n` 编码 60 帧后退出。程序会打印驱动实际返回的尺寸和 stride，以实际日志为准。`-f` 不能保证传感器一定切换到相同帧率，驱动可能不支持修改采集帧率。

```bash
ffprobe -v error -f hevc -count_frames \
  -show_entries stream=codec_name,width,height,nb_read_frames \
  -of default=noprint_wrappers=1 learn_imx415.h265
```

解释：与文件测试相同，检查摄像头输出是否为完整的 60 帧 HEVC 和实际尺寸。码流只有视频，没有音频，也没有 MP4 容器。

### 5.3 板端恢复 FFmpeg / HDMI，电脑重连 RTSP

开发板 Bash：

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py start
```

解释：重新启动 FFmpeg 硬编直播；不带配置时沿用保存的参数。先确认摄像头 C 程序已经退出。

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py preview-start
```

解释：启动板端 HDMI 播放器，它读取 RTSP，不再次采集摄像头。

电脑 PowerShell：

```powershell
ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay rtsp://192.168.2.221:8554/imx415
```

解释：`ffplay` 播放直播；`-rtsp_transport tcp` 使用 TCP；`-fflags nobuffer` 与 `-flags low_delay` 减少缓存；URL 指向板端 8554 的 imx415 流。IP 变化时替换地址。

### 5.4 把 C 程序录制的文件拿回电脑看

恢复直播后，在电脑另一个 PowerShell 中操作。如果这是新开的终端，先设置它自己的 ADB 变量：

```powershell
$adbPath = 'C:\Users\dvsense_docker\Desktop\work\RK3588\Tools\platform-tools\adb.exe'
```

解释：新终端不会继承你在另一个终端里手动赋的变量，这里重新保存 ADB 路径。

```powershell
New-Item -ItemType Directory -Path .\recordings -Force
```

解释：在电脑当前目录建立录像保存文件夹；`-Force` 允许目录已经存在，不会删除已有内容。

```powershell
& $adbPath pull /userdata/av_dev/mpp_route2/learn_imx415.h265 .\recordings\
```

解释：`adb pull` 将板端 C 程序输出文件复制到电脑，两个参数分别是板端源文件与电脑目标目录。它不占用摄像头，实时画面可以继续播放。若先前使用了不同文件名，替换源路径。

```powershell
ffplay -f hevc .\recordings\learn_imx415.h265
```

解释：打开电脑上的录像文件；`-f hevc` 指定裸 H.265。这次是文件回放，不是 TCP 直播。查看纹理、运动和颜色是否正确；裸码流没有完整容器时间轴，准确帧数仍以 ffprobe 检查为准。

## 6. 把 C 程序的每一层讲清楚

### 6.1 V4L2：把一帧借到用户空间

`capture_open()` 打开设备并用 `VIDIOC_QUERYCAP` 核对多平面采集和流式能力；用 `VIDIOC_S_FMT` 请求 NV12M；读取驱动实际返回的尺寸、两平面 stride；再申请 4 个采集缓冲。每个缓冲的 Y/UV 分别 mmap，全部 QBUF 后 STREAMON。

`capture_dequeue()` 先 poll 等一帧，再 DQBUF 取出缓冲索引与各平面的 `bytesused/data_offset`。`capture_queue()` 把使用完的那帧归还驱动，让它可以继续采集。`capture_close()` 停流、解除映射并关闭设备。

**NV12 与 NV12M 的像素含义相同，但内存接口不同。** NV12 是 Y 后接交错 UV；当前驱动的 NV12M 用两个平面描述这两部分，不能假定 UV 就在 Y 指针后面。1080p 的有效 Y 是 2073600 字节，UV 是 1036800 字节，每帧有效图像总共 3110400 字节。

### 6.2 MppEncCfg：告诉编码器如何工作

`h265_encoder_open()` 执行 `mpp_create → mpp_init(HEVC) → mpp_enc_cfg_init → GET_CFG → SET_CFG`。其中 `ctx` 是编码上下文，`mpi` 是函数接口表，`cfg` 是配置对象。

| 配置键 | 当前含义 |
| --- | --- |
| `prep:width/height` | 有效画面尺寸 |
| `prep:hor_stride/ver_stride` | MPP 输入缓冲的对齐宽度/高度 |
| `prep:format` | `MPP_FMT_YUV420SP`，即 NV12 |
| `rc:mode` | CBR |
| `rc:bps_target/max/min` | 目标码率与控制范围；不是每秒字节数 |
| `rc:fps_in/out_*` | 编码器的帧率配置 |
| `rc:gop` | 当前等于 fps，即 30 fps 时约每 30 帧一个 GOP |
| `codec:type` | `MPP_VIDEO_CodingHEVC` |

程序取得 VPS/SPS/PPS 并先写到文件，配置每个 IDR 附带参数集。解码器需要这些参数集理解码流。不要把 H.264 的 `profile/level` 配置直接搬进 H.265 配置。

### 6.3 MPP Buffer：stride 为什么不是 height

本程序把输入的宽高向上对齐到 16。1920×1080 对应 MPP 缓冲 1920×1088；有效画面仍是 1920×1080。UV 在目标缓冲中的起点是 `stride×vstride`，不能用 `width×height` 替代。

`h265_encoder_frame()` 按行把 V4L2 的 Y/UV 拷入 MPP 输入缓冲，源 stride 与目标 stride 分别使用各自的值。随后建立 MppFrame，设置格式、宽高、stride、PTS 和最后一帧 EOS。

### 6.4 put_frame / get_packet：一帧进去，一帧压缩结果出来

`encode_put_frame()` 提交帧；`encode_get_packet()` 等待编码输出。若一帧拆成多个分片，当前实现循环读到帧末 EOI，不能只保存第一片。`write_packet()` 从包的当前位置写入长度所指的数据，然后释放包。

当前采用同步的一帧一帧处理：本帧编码结果取完后再覆盖 MPP 输入缓冲，并归还 V4L2 缓冲。这便于学习；将来改成异步队列或多线程时必须重新管理缓冲生命周期，不能简单保留同一个输入 Buffer 并让不同线程同时覆写。

PTS 目前按 `帧号×1000000/fps` 生成。裸 `.h265` 文件不保存 MP4 那样的容器时间轴；以后做音视频同步要保留真实采集时间戳并传递给封装层。

### 6.5 文件测试入口

`yuv_mpp_enc.c` 只负责按 `width×height×1.5` 从文件读取一帧，然后把 Y/UV 指针交给同一个 `h265_encoder_frame()`。因此文件测试能通过、摄像头测试失败时，应优先排查 V4L2 节点、占用、格式与两平面数据，而不是立即改 MPP 配置。

## 7. 之前具体改了什么

| 之前的实现问题 | 现在的处理 | 改动文件 |
| --- | --- | --- |
| 单平面 V4L2 采集假设与本板驱动不符 | 改成 CAPTURE_MPLANE / NV12M，两平面独立 mmap 和长度校验 | `v4l2_mpp_enc.c` |
| 两个示例的 MPP 初始化和配置不一致 | 提取共用 H.265 编码引擎 | `mpp_h265.c/.h` |
| 使用与板端安装包不匹配的头文件/API 写法 | 按板端 MPP 开发文件重新编译并验证 | 头文件与 Makefile |
| 输入尺寸与缓冲对齐混用 | 分别保存有效宽高、对齐 stride、源两平面 pitch | 两个核心 C 文件 |
| 输出成功缺乏实测依据 | 实际跑测试图与 IMX415，并统计可解码帧数 | 验证流程 |
| 更新 C 代码可能覆盖板上旧示例 | 新增独立 `mpp_route2` 部署目录 | `tools/deploy/deploy.ps1` |

目前未实现：C 程序 HDMI 预览、C 程序 TCP/RTSP 推流、ROI、运行时动态码率、音视频同步、DMA-BUF 零拷贝以及自动重启服务。这些不影响已经验证的文件编码闭环。

## 8. 你如何改动，先从参数实验开始

### 8.1 不改源码：比较 2 与 4 Mbit/s

在暂停当前直播后，板端运行：

```bash
./v4l2_mpp_enc -d /dev/video44 -o learn_2mbps.h265 -c h265 -w 1920 -h 1080 -b 2000000 -f 30 -n 300
```

解释：录制约 10 秒；所有选项同第 5 节，仅目标码率改为 2 Mbit/s，帧数改为 300。记录程序打印的实际耗时与总字节数。

```bash
./v4l2_mpp_enc -d /dev/video44 -o learn_4mbps.h265 -c h265 -w 1920 -h 1080 -b 4000000 -f 30 -n 300
```

解释：用相同分辨率和帧数录第二段，目标改为 4 Mbit/s。保持摄像头朝向与场景活动尽量一致；两条命令依次执行。完成后立即按第 5.3 节恢复画面。CBR 也不保证非常短的片段恰好达到目标，比较文件大小、细节和实际平均码率一起判断。

### 8.2 改源码：改变 GOP

在电脑修改根目录 `examples/mpp_c_api/mpp_h265.c` 中这行：

```c
cfg_s32(enc, "rc:gop", fps)
```

例如把最后的 `fps` 改成 `fps * 2`，在 30 fps 配置下 GOP 由 30 改为 60。这是源码片段，不是终端命令。GOP 较长通常可以减少频繁关键帧带来的码流开销，但直播中途加入的等待时间也可能增加。先只改这一项，保留基准输出，再比较结果。

在电脑 PowerShell、项目根目录打包修改后的源码：

```powershell
python .\tools\release\package_project.py
```

解释：直接从当前唯一源码生成 `releases/av_dev-source.zip`，不再复制第二份可编辑目录；重复执行会更新该 ZIP，不会上传或启停开发板。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools/deploy/deploy.ps1 -BuildExamples
```

解释：重新上传源码并在板端增量编译；各选项含义同第 3 节。正在运行的直播管线与这些 C 二进制无关，因此编译不会让当前两端画面切换成 C 程序。之后依次执行文件测试、短摄像头测试、恢复当前 FFmpeg 直播。

### 8.3 不要随手改的项

不要为减小分辨率直接删两平面处理；不要把 UV 起点换回 `width×height`；不要把所有数据一次 memcpy 后认为没有 stride；不要因为设置 `-f 60` 就认定传感器实际已到 60 fps；不要改 Makefile 去使用另一版本 MPP 头文件却继续链接当前运行库。

## 9. 下一步按什么顺序开发

1. **先做参数实验与更长验证**：同场景比较 2/4 Mbit/s 与 GOP 30/60；检查输出尺寸、完整帧数、耗时、平均码率。保存日志，再做分钟级验证。当前 60 帧测试只证明短链路可用。
2. **补足可维护性**：采集时间戳、编码耗时统计、信号退出与资源清理、有限等待和超时恢复。避免进程卡住后摄像头一直被占用。
3. **运行时动态码率**：在共用编码器层增加更新函数，同时更新 `rc:bps_target/max/min`，再调用 `MPP_ENC_SET_CFG`。先在同步帧循环的帧边界应用，记录切换帧号；这与重启程序时改变 `-b` 是两种能力。
4. **自研 TCP 推流与预览**：把 `write_packet()` 抽成输出回调，支持文件和网络；处理 partial send、断开重连、客户端加入时的参数集/关键帧、慢客户端背压。HDMI 预览需要独立显示支路，不能让显示或网络卡住采集线程。完成前继续用已验证的 FFmpeg 直播做实时显示。
5. **零拷贝与 ROI**：先核对 NV12M 两平面 DMA-BUF 导出的布局能否直接匹配 MPP；若不能需要重排/转换。ROI 按当前 MPP 版本的结构与元数据接口实现，不能把其它 SDK 的示例直接复制进来。
6. **再评估路线三**：目前板端 FFmpeg 没有 rkmpp 编码器，未发现 Rockit 开发组件；需要匹配的 SDK/工具链与部署验证，不应将 `libx265` 软件编码当作硬编。

建议你眼下先完成第 1 项，然后开发第 3 项。这样可以用现有文件闭环判断改动是否正确，再扩展网络与多路功能。

## 10. 常见失败怎么定位

| 现象 | 优先检查 |
| --- | --- |
| PowerShell 不认识 `DISPLAY=:0` | 命令执行在错误终端，转到板端 Bash |
| `Device or resource busy` | FFmpeg、07 或其它进程尚占用摄像头，重新用 lsof 检查 |
| `Address already in use` | 原 07 仍监听 5000，核对 ss 的 PID |
| `create H.265 output: File exists` | 用新输出文件名，程序故意拒绝覆盖 |
| `Expected two-plane NM12` | 选择的节点/驱动布局不匹配，先查看实际格式 |
| `Invalid NV12 plane size or stride` | 驱动 bytesused/data_offset 或行步长与假设不符 |
| `NV12 input ended at frame ...` | 文件帧数不足，或输入宽高不是文件实际尺寸 |
| `MPP config ... failed` | 配置键或取值与当前 MPP 版本不匹配 |
| 程序不退出/取包一直等待 | 当前 MPP 输出用阻塞模式；调试时加外部 timeout，后续应实现有限等待恢复 |

## 11. 备份与 Git 文件范围

本次修改前的完整方案、源码和 ZIP 已保存在项目的 `backups/before_route2_guide_20261012_172937/`，`SHA256_manifest.json` 记录 18 个原文件的校验值。它保存的是开始写本说明之前的当前版本，不能凭空恢复未保留的更早 HTML。

Git 跟踪根目录规范源码、部署脚本、方案页面和这份说明；SDK、编译产物、录像、本机状态快照、交付副本、ZIP、临时目录和本地备份排除。Git 历史用于追踪今后源码变更，本地备份用于保留本次更新前的完整交付。
