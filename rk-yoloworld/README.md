# RK3588 YOLO-World 实时检测：程序说明与操作手册

本工程用于 EVM3588、IMX415/con7、`/dev/video44`，采用 V4L2＋RGA＋RKNN＋H.264 硬编。摄像头只打开一次，目标框画在对应原帧上；电脑和开发板 HDMI 可以同时观看检测结果。

## 1. 工程到底在哪里

**唯一日常开发目录：**

`C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev\rk-yoloworld`

保留它作为 `av_dev` 下的独立子工程，可以沿用已有 Git 仓库和构建环境。此次实际检查，`RK3588` 下没有与 `av_dev` 同级的另一个 `rk-yoloworld`。之前发现的另一个同名目录，是源码 ZIP 解压后的构建验证副本，现已归档到 `.cache/archived-build-check/source-tree/`，不再与正式工程同名。

需要分清四个位置：

| 位置 | 内容 | 应该如何使用 |
|---|---|---|
| 电脑 `av_dev/rk-yoloworld/` | 本工程源码、配置、工具和文档 | **只在这里修改源码** |
| 电脑 `rk-yoloworld/dist/` | 编译好的 ARM64 程序、模型、私有库、交付 ZIP | 由构建/打包工具生成，不作为第二份源码维护 |
| 电脑 `rk-yoloworld/inputs/original_deploy/` | 你提供的网盘原始解压包，含作者原 demo | 留作输入和追溯，不是当前运行程序；已从工程根目录移入 `inputs/` |
| 板端 `/userdata/rk-yoloworld/` | 实际执行的 ARM64 程序、模型和库 | 通过板端 Linux 终端运行；不是 Windows 的 C 盘路径 |

Docker 中的 `/project` 是这个电脑子目录的挂载路径，也不是另一份日常工程。ZIP 内携带的源码是交付快照，不要再解压成平行的日常开发目录。

## 2. 先照这个顺序打开检测画面

正常使用需要一个电脑视频窗口、一个板端检测终端；查看指标时再开一个监测终端。下面所有命令都注明了执行位置。Windows PowerShell 的提示符是 `PS C:\...>`；开发板 Linux 提示符通常是 `root@ema:~#`。

### 2.1 电脑先打开接收窗口

**Windows PowerShell：**

```powershell
Set-Location 'C:\Users\dvsense_docker\Desktop\work\RK3588\av_dev\rk-yoloworld'
```

含义：进入电脑上的正式工程目录。`Set-Location` 是 PowerShell 切换目录命令。

**仍在这个 Windows PowerShell 终端：**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\receive_windows.ps1 -Port 1235
```

含义：调用接收脚本打开 ffplay 窗口。`powershell.exe` 必须写在最前面；`-NoProfile` 不加载个人配置；`-ExecutionPolicy Bypass` 只对新进程生效；`-File` 指定脚本；`-Port 1235` 监听本机 UDP 1235 端口。脚本使用 PATH 中已有的 `ffplay.exe`。关闭窗口或按 Q 只关闭电脑播放，不停止板端检测。

如果 ffplay 不在 PATH，**Windows PowerShell、相同目录**可指定其实际位置，例如：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\receive_windows.ps1 -Port 1235 -Ffplay 'D:\FFmpeg\bin\ffplay.exe'
```

含义：`-Ffplay` 指定 ffplay 可执行文件的路径；示例中的 D 盘路径需要替换成你实际安装的位置，其他参数与上一条相同。

电脑和板子必须可以互通。当前 `config.env` 接收地址是 `192.168.2.165:1235`；换电脑或 IP 变化时，要修改**板端**配置中的 `DESTINATION`。Windows 防火墙需允许 ffplay 在当前局域网接收 UDP；工程不会自动改防火墙。

### 2.2 进入开发板终端

已有 `root@ema` 终端时直接用它。还没有时，**另开一个 Windows PowerShell 终端**：

```powershell
ssh root@192.168.2.221
```

含义：通过 SSH 登录板子；`root` 是板端账户，`192.168.2.221` 是当前板端 IP，首次连接应核对主机指纹，密码在提示时输入。登录成功后，下列命令在板端 Linux 执行。ADB shell 进入板端后也可以执行相同的 Linux 命令。

**开发板 Linux：**

```bash
cd /userdata/rk-yoloworld
```

含义：进入板端部署目录。不要在这里输入 `C:\Users\...`，也不要把 Linux 的 `DISPLAY=:0` 赋值语法直接输入 PowerShell。

### 2.3 同时在板端 HDMI 和电脑显示检测结果

**开发板 Linux，目录 `/userdata/rk-yoloworld`：**

```bash
python3 tools/run_with_restore.py --seconds 0 --hdmi
```

含义：`python3` 运行板端恢复包装器；`--seconds 0` 表示持续检测直到 Ctrl+C；`--hdmi` 同时打开板端检测画面。电脑接收窗口需按 2.1 节先打开。

执行顺序是：先检查模型和 9 个绑核 context，再保存原视频状态，通过原控制接口释放摄像头，启动实时检测、H.264 推流与 HDMI 预览。正在 MP4 录像时拒绝切换，避免破坏录像。

**在这个检测终端按 Ctrl+C**，程序正常回收摄像头、推理资源、H.264 编码和检测 HDMI 子进程，然后恢复测试前的 H.265/RTSP/HDMI 状态。不要用 `kill -9` 代替正常结束。

需要只跑 5 分钟时，**同一板端目录**改用：

```bash
python3 tools/run_with_restore.py --seconds 300 --hdmi
```

含义：`300` 是检测运行时间，单位秒，不包括前面的模型准备时间；到时自动退出并恢复。不要与上一条同时运行。

只需要电脑检测画面时，**同一板端目录**：

```bash
python3 tools/run_with_restore.py --seconds 0
```

含义：不加 `--hdmi`，只向电脑推流，省去板端检测解码与显示的资源开销。启动期间原 H.265 HDMI 会暂停，退出后按保存状态恢复。

### 2.4 在电脑终端看实时指标

**另开 Windows PowerShell：**

```powershell
ssh -t root@192.168.2.221 python3 /userdata/rk-yoloworld/tools/monitor.py
```

含义：SSH 在板端执行只读监测程序；`-t` 分配终端，使面板原地刷新。它不运行 NPU 检测，也不打开摄像头，只读取运行数据。按 Ctrl+C 只退出监测，检测继续运行。

也可以在**另一个已经登录的板端 Linux 终端**执行：

```bash
python3 /userdata/rk-yoloworld/tools/monitor.py
```

含义：从任何板端工作目录启动同一监测程序，默认每秒刷新一次。第一份采样没有差分基线，部分 CPU/FPS 显示“不可用”，下一秒开始出现；应用退出或日志过期后不会把旧 FPS 当成当前值。

当前 Windows 检测画面入口是 ffplay 接收脚本，资源面板是这个终端监测工具。原 PySide6 上位机仍控制原 H.265 RTSP 链路；其原视频窗口不会自动变成 YOLO 检测画面，检测期间也不要从旧上位机抢先启动另一条摄像头采集。

## 3. CPU、NPU、内存和九个线程该怎么看

### 3.1 首先纠正线程与进程的概念

检测主体是 **1 个 Linux 进程，16 个应用线程**，其中 **9 个 RKNN 推理线程**。RK3588 只有这里使用的 **3 个 NPU 核**，每核有 3 个 context 排队使用，不是 9 个独立 NPU。CLIP 在开始时执行并释放，不占用视频阶段的第十个推理线程。

| worker | Linux 线程名 | 绑定的 NPU 核 | core mask |
|---:|---|---:|---:|
| 0 | `infer0-npu0` | 0 | 1 |
| 1 | `infer1-npu1` | 1 | 2 |
| 2 | `infer2-npu2` | 2 | 4 |
| 3 | `infer3-npu0` | 0 | 1 |
| 4 | `infer4-npu1` | 1 | 2 |
| 5 | `infer5-npu2` | 2 | 4 |
| 6 | `infer6-npu0` | 0 | 1 |
| 7 | `infer7-npu1` | 1 | 2 |
| 8 | `infer8-npu2` | 2 | 4 |

每次启动后的 TID 会改变，以监测面板为准。`rknn_set_core_mask` 绑定失败就停止初始化，不悄悄换核。它指定 **NPU 核**，并没有把该 Linux 线程固定到某个 CPU 核。

这些计数由并发线程更新，一份秒级快照的各 worker 合计与总计可能有瞬时差异；看连续时间窗口，不用单个采样的微小差异推断丢任务。

### 3.2 监测面板每项的含义

| 显示项 | 数据来源与解释 |
|---|---|
| 检测 PID | 当前部署目录中实际运行的检测进程；不把其他同名工程的进程算进来 |
| 检测 CPU | `/proc/PID/stat` 的用户/内核 CPU 时间增量；**一个逻辑核=100%**，200% 约占两个核，不代表整板 CPU 已满 |
| 整板 CPU | `/proc/stat` 的差分，按整机容量归一到 0～100%；与上面的口径不同 |
| 检测 RSS | 该进程当前驻留内存，单位 MiB；不含独立 FFmpeg、播放器和全部 NPU 内核分配 |
| 整板内存 | `/proc/meminfo` 的 `MemTotal - MemAvailable`；与单进程 RSS 不同 |
| 三核 NPU% | `/sys/kernel/debug/rknpu/load`，每核总忙碌率；例如 94%/95%/96% 表示三核都很忙 |
| 每 worker CPU% | `/proc/PID/task/TID/stat` 的差分，只是该推理线程消耗的 **CPU** 时间 |
| 每 worker 推理 FPS / 累计完成 | C++ 每线程完成计数的差分 / 累计值，按统计中的单调时间间隔计算 |
| 编码 / HDMI 解码 / HDMI 播放 | 独立子进程的 PID、CPU 和 RSS，避免误以为检测 RSS 包含了它们 |
| 网口 TX/RX | 所选网口字节增量转成 Mbit/s，包含该网口的全部流量；默认 `eth1` |
| TX 占用 | `TX Mbit/s ÷ 网口协商 Mbit/s × 100%`；千兆链路发送 20 Mbit/s 约为 2% |
| HDMI UDP socket 丢包 | 本机 1236 接收 socket 的内核累计丢包，只在检测 HDMI 运行时可用；不等于摄像头序号缺口 |
| 统计新鲜度 | 只接受当前检测 PID 的日志；超过 3 秒则实时 FPS 标为无数据/已过期 |

**目前驱动没有提供“9 个 context 各自精确占了多少 NPU 百分比”的接口。** 不会把每核 95% 平均除以 3，伪造每个线程 31.7% 的 NPU 占用率。判断负载应结合：三核总忙碌率、各线程完成 FPS、累计完成量、CPU 开销及排队丢弃。

线程等待 NPU 时，自己的 CPU 占用可能很低，但 NPU 已接近满载；这是正常现象。9 个线程共享进程地址空间，也不能把进程 RSS 在每个线程上重复相加。某个 worker 暂时完成较少，也可能是 NPU 调度、CPU 后处理或队列竞争，不单凭一秒采样判断绑核失效。

### 3.3 记录 CSV，或提供机器可读数据

**板端 Linux，目录 `/userdata/rk-yoloworld`：**

```bash
python3 tools/monitor.py --interval 1 --csv logs/resources-session01.csv
```

含义：每 1 秒显示并保存一份资源采样；`--csv` 指定输出文件，自动创建父目录，以 UTF-8 BOM 保存，方便 Windows Excel 打开。文件以新建/覆盖方式写入，请每次使用不同文件名。Ctrl+C 会关闭并刷新 CSV，不停止检测。

**同一板端目录：**

```bash
python3 tools/monitor.py --json --count 10
```

含义：`--json` 每行返回一个 JSON，便于未来上位机接入；`--count 10` 采样 10 次后退出，省略或写 0 则持续采样。没有 NPU 权限、进程未运行或统计过期时用 `null`/状态字段表示缺失，不假装占用为 0。

网线接到其他接口时，**同一板端目录**可指定：

```bash
python3 tools/monitor.py --interface eth0
```

含义：只把网口统计切换为 `eth0`；不修改路由、不改变视频目标地址，也不会改变摄像头参数。

需要交叉核对时，以下命令均在**板端 Linux、任意目录**执行：

```bash
cat /sys/kernel/debug/rknpu/load
```

含义：一次读取驱动公开的三核负载；不是单 context 性能剖析。无权限或节点不存在时查看监测面板的“不可用”提示，不为此更换驱动。

```bash
top -H
```

含义：`-H` 让 top 按线程显示；可查找 `infer0-npu0`～`infer8-npu2`。CPU% 是 Linux CPU 时间，不是 NPU%。“九个线程”不会在普通进程视图里出现为九份独立模型进程。

```bash
free -h
```

含义：查看整板内存；`-h` 采用易读单位。它不等于检测进程 RSS，也不能用来直接得到每个 RKNN context 的独占内存。

## 4. 实际视频与线程数据流

```text
IMX415 → CSI/ISP → /dev/video44 NV12M
  → capture：验证、复制到自有 NV12 帧、立即归还 mmap 缓冲
  → 原帧队列（深度 2）
  → preprocess ×2：RGA letterbox / 颜色转换
  → 待推理队列（深度 2）
  → infer ×9：独立 RKNN context，使用启动时缓存的文本特征
  → 最新结果槽（1）：只接受递增序号
  → render：在该结果持有的原始 NV12 图上画框
  → 最新输出槽（1）
  → NUT/rawvideo：携带真实采集 PTS
  → FFmpeg h264_rkmpp：一次硬编
      ├─ MPEG-TS/UDP → 电脑 192.168.2.165:1235 → ffplay
      └─ 可选 MPEG-TS/UDP → 本机 127.0.0.1:1236
          → FFmpeg h264_rkmpp 硬解 → RGA 1920×1080
          → 带 PTS 的 NUT/rawvideo → 板端 ffplay → HDMI
```

| 应用线程 | 数量 | 主要工作 |
|---|---:|---|
| 主线程 | 1 | 参数、模型初始化、信号、超时和退出协调 |
| capture | 1 | V4L2 取帧、校验、逐行复制和 QBUF |
| preprocess | 2 | 各用独立 DMA/RGB 缓冲完成预处理 |
| infer0～infer8 | 9 | 独立 context、输入/输出资源和计数 |
| render | 1 | 按对应原帧画框、还原 letterbox 坐标 |
| output | 1 | 写完整 NUT 包，最多 60 fps，隔离编码背压 |
| stats | 1 | 每秒输出 JSON，含每个 worker 的 TID/core/completed |

总共 **15 个工作线程＋1 个主线程=16 个显式应用线程**。RKNN 库内部可能另有线程；编码器、HDMI 解码器、ffplay、恢复包装器、监测工具分别是其他进程，不混入这个计数。

### 4.1 NPU 忙时为什么丢帧

摄像头约 60 fps 并不代表当前模型每秒能检测 60 帧。原帧和待推理队列满时丢掉最旧的**等待任务**；已经提交的最多 9 个推理任务正常完成，不强制打断。各结果始终持有自己的原图，所以不会把旧检测框贴到新画面。

9 个推理任务会乱序结束。结果槽记住历史最大序号，旧结果即便晚到也不能覆盖已显示的新结果；输出严格递增，不等缺失帧补齐。因此推理完成 FPS 大于有效输出 FPS，不能把两者相加或混用。

NV12 池为 24 个槽，模型 RGB 池为 16 个槽，均复用。池耗尽时仍会取走并归还驱动缓冲，单独记账，不无限申请内存。

### 4.2 V4L2、RGA 和模型的实现细节

采集支持单平面 NV12 和本板实际的 NV12M 双平面，逐 plane mmap；验证 stride、映射长度、`bytesused`、`data_offset`，按有效行宽复制并立即 QBUF。`bytesused` 包含 offset，不会把平面填充当成图像。部分初始化失败或退出时释放已获得资源。

本板 video44 不支持设置 `S_PARM`，程序另外查询已核对的 `/dev/v4l-subdev2` 传感器帧间隔，并用成功取帧计数测实时 FPS；不把请求 60 直接写成实测 60。STREAMON 延后到模型/池/RGA/编码准备好后；跳过前 5 个有效帧，启动阶段序号跳变与运行阶段缺口分别统计。

当前 BSP 的 full-range CSC 直接转换路径不能正常满足颜色要求，因此先由 RGA 缩放 NV12，在模型尺寸的小图上由 CPU 把 full-range 映射为 limited-range，再由 RGA BT709-limited CSC 转 RGB。不是全程零 CPU。驱动矩阵标记 Default，本版按 HD BT.709 处理，并非对相机做了物理色彩标定。纯黑、白、红、绿合成检查通过，详情见 [VALIDATION.md](VALIDATION.md)。

CLIP 模型是 batch=1：启动时按每个有效类别运行一次，生成只读文本特征，然后释放 CLIP context。视频阶段只运行 YOLO-World。9 个 context 独立管理输出，逐次释放，后处理屏蔽填充类别。

### 4.3 时间戳和双端显示

NUT 把真实单调采集 PTS 交给 FFmpeg；编码使用微秒时基和 passthrough，不把 20 多 fps 的检测结果当成固定 60 fps 裸流加速播放，也不重复帧凑 60。

`--hdmi` 通过 FFmpeg tee 将同一份压缩结果发往电脑和本机，没有第二次编码；板端 HDMI 读取这份压缩流，不再次打开摄像头。检测输入/电脑压缩流为 2560×1440，HDMI 解码后缩放显示为 1920×1080。新增本机分支有发送节流和接收缓冲，监测工具会单独报告 socket 丢包。HDMI 的原始显示管道也携带 NUT 时间戳，不按固定 60 fps 改写检测节奏。

管道每包最多等待 2 秒；正常停止写完已开始的包再退出，防止半个 NV12 包破坏最后一帧。编码器退出或真正阻塞会报错并清理自己启动的进程，不终止无关 FFmpeg。HDMI 失败时查看 `logs/detection-hdmi.log`，不自动切换到软件解码。

## 5. 每个子目录放什么

```text
rk-yoloworld/                     ← 正式开发根目录
├─ src/                           ← 自研 C++ 实现，日常主要修改这里
├─ include/                       ← 公共类型与模块接口
├─ tests/                         ← 逻辑、模拟 API、板端与监测测试
├─ tools/                         ← 构建、运行恢复、监测、验收和打包
├─ licenses/                      ← 依赖许可证，不是可执行代码
├─ inputs/original_deploy/         ← 原始网盘输入包，只在本地保留
├─ vendor/                        ← 固定第三方源码归档、tokenizer、头文件
├─ build/                         ← CMake/交叉编译中间文件、测试结果
├─ dist/                          ← ARM64 运行文件与发布 ZIP
│  ├─ lib/                        ← 私有 RKNN/RGA/NUT 库
│  ├─ model/                      ← CLIP、YOLO、类别文件和示例图片
│  └─ package-libraries/          ← 原包 RGA 候选，未选作运行库
├─ logs/                          ← 拉回电脑的实机 JSONL、CSV、日志
├─ .cache/                        ← 下载、格式化和旧重建验证缓存
├─ README.md                      ← 本手册，唯一主要操作入口
├─ VALIDATION.md                  ← 实测数据、版本与未解决限制
├─ todo.md                        ← 实施清单
├─ THIRD_PARTY.md / LICENSE        ← 依赖来源及授权信息
├─ sources.lock.json              ← 固定依赖版本、下载位置与校验值
├─ CMakeLists.txt                 ← C++ 构建目标和测试目标
├─ config.env                     ← 下次启动使用的板端参数
├─ run_realtime_yolo_world.sh      ← 普通启动入口，不抢占其他摄像头进程
└─ receive_windows.ps1            ← 电脑 ffplay 接收入口
```

板端解压后的运行目录还会有根目录 `rknn_yolo_world_realtime`、`lib/`、`model/` 和 `state/`。`state/` 保存测试前配置、恢复快照、调度恢复日志、检测 HDMI PID 等；它不是源码。运行时不要删除它，否则会失去恢复依据。

`inputs/`、`vendor/`、`build/`、`dist/`、`logs/`、`.cache/` 和运行 `state/` 不进入 Git。`inputs` 原 demo、`dist` 新程序和板端部署程序用途不同；不要以文件名相似为由混用。`lib` 中 `.so`、`.so.1`、`.so.2` 等别名用于不同 SONAME 兼容，同一组件校验值相同，不代表装了三套不同版本。

### 5.1 src/：六个 C++ 文件

| 文件 | 主要程序与职责 | 常见修改方向 |
|---|---|---|
| [src/main.cpp](src/main.cpp) | `options` 参数；CLIP/9 context 初始化；16 线程组织；队列/池；错误与信号；每秒统计和 worker TID | 调整应用流程、统计字段、线程数。改变 worker 数必须同步绑核、资源上限、监测及测试 |
| [src/capture.cpp](src/capture.cpp) | `Capture`：QUERYCAP、S_FMT、REQBUFS、mmap、QBUF、STREAMON、poll、DQBUF 与清理；传感器帧间隔 | 摄像头节点、格式兼容、stride/offset、驱动缺口排查 |
| [src/preprocess.cpp](src/preprocess.cpp) | `Preprocess`：DMA32 缓冲、cache sync、RGA letterbox、范围映射、RGB 输出与坐标变换参数 | 新模型尺寸、颜色路径、缩放方式；修改后做纯色与框坐标测试 |
| [src/model.cpp](src/model.cpp) | 动态加载 RKNN；查询模型属性；`encode_text`；`Detector` 独立 context/绑核/输入输出；量化后处理/NMS | 换模型、文本容量、阈值、输出头结构。不能只换文件而忽略张量形状 |
| [src/draw.cpp](src/draw.cpp) | `draw_nv12`：坐标反变换、NV12 框/文字、类别与置信度 | 框颜色、线宽、标签；当前内置字库是 ASCII，非 ASCII 显示问号 |
| [src/output.cpp](src/output.cpp) | `Nut` 时间戳复用；`encoder_arguments`；`Encoder` 独立 FFmpeg 环境、单次硬编、tee 双输出、背压、子进程回收 | 传输/封装/编码参数；不在这里再读摄像头或再次做推理 |

### 5.2 include/：四个头文件

| 文件 | 作用 |
|---|---|
| [include/core.hpp](include/core.hpp) | `Frame/Box/Plane` 数据结构；`Queue` 有界丢旧队列；`Latest` 历史最大序号保护；`Pool` 复用租借；NV12 plane 校验/复制；IoU/NMS；单调时钟 |
| [include/capture.hpp](include/capture.hpp) | `Capture` 接口，超时返回 false，坏帧先归还缓冲再抛错 |
| [include/model.hpp](include/model.hpp) | 文本特征 `Text`、`Detector`、`Preprocess` 和画框接口，隔离 RKNN/RGA 细节 |
| [include/output.hpp](include/output.hpp) | `OutputConfig`、可测试的编码参数构造、`Nut` 和 `Encoder` 接口 |

### 5.3 tools/：按使用目的查找

| 文件 | 作用与使用环境 |
|---|---|
| `run_with_restore.py` | **板端常用入口**：模型预检、保存原状态、录像保护、临时接管、可选 HDMI、退出恢复；使用原 avctl 接口 |
| `hdmi_preview.py` | 板端检测专用 VPU 解码/RGA/NUT/ffplay 管理，由上一个入口导入；本身不采集相机、不创建第二编码器 |
| `monitor.py` | **板端只读监测入口**：CPU/RSS/NPU/9 worker/网口/新鲜度，终端、JSON、CSV 三种输出 |
| `prepare_sources.py` | Windows/Linux 准备并校验固定上游依赖，提取到 vendor/build；不控制相机 |
| `verify_sources.py` | 检查锁定的源码和头文件 SHA-256，防止依赖悄悄变动 |
| `import_deploy.py` | 从输入 ZIP/解压目录按白名单导入模型/runtime/类别；检查路径，不运行作者 demo |
| `Dockerfile` | Ubuntu 20.04 AArch64 交叉编译环境，匹配板端 GLIBC 2.31 |
| `build_linux.sh` | 并行 4 任务，构建私有 NUT 库和 ARM64 程序；显式 `-O3 -DNDEBUG`，更新 dist |
| `record_build.py` | 记录工具链、选项、源文件/ELF 校验值，拒绝缺少优化选项的发布构建 |
| `package_release.py` | 生成部署 ZIP、完整源码 ZIP 和 SHA-256；不打包实机日志、原始输入或构建缓存 |
| `verify_release.py` | 检查 ZIP CRC、重复条目、源文件与构建清单、库/可执行文件与交付包一致性 |
| `board_link.py` | 电脑通过已有 ADB 40 读/传板端文件；不存储 SSH 密码，其他自动验收工具复用 |
| `start_board_test.py` | 电脑维护工具：传新程序/运行工具并后台启动有恢复保护的板端测试；支持 `--hdmi` |
| `stop_board_test.py` | 核对自己保存的包装器 PID/命令，再发送 SIGINT；不批量杀 FFmpeg |
| `test_status.py` | 电脑读取测试进度与最近日志；不会修改板端状态 |
| `collect_results.py` | 电脑拉回最新测试 JSONL/日志/恢复快照，生成本地 CSV 和均值摘要；不会把最新摘要当成所有旧测试结果 |
| `probe_models.py` | 真实板端模型/RGA/9 context 预检，不打开摄像头 |
| `test_picture.py` | 真实板端单 context 与 9 context 同时推理图片一致性、有效类别屏蔽检查 |
| `test_host.sh` | Linux 主机 C++ 逻辑/模拟采集/模拟 RKNN 测试，`--sanitize` 开启 ASan/UBSan |
| `test_board_primitives.py` | 真实 ARM64 的基础逻辑、RGA 纯色、NUT PTS、输出异常测试；不采集摄像头 |
| `test_rebuilt_rga.py` | 验证从锁定源码重新构建的 RGA 库，而不只验证已有库 |
| `test_lifecycle.py` | 真实接管、定时停止、SIGINT、网络采样及恢复回归，会短暂中断原视频 |
| `verify_restoration.py` | 核对旧链路、解码帧进度、相机占用、残留进程、启动分区哈希；`--restore` 会启动本板保存的 H.265 默认配置 |
| `check_devices.py` | 检查检测/硬编进程实际加载的库、设备 FD、线程数 |
| `sniff_sample.py` | 只读抓取本板发往电脑 UDP 1235 的压缩负载，供离线验证；不再打开相机 |
| `analyze_sample.py` | 检查完整关键帧片段的尺寸、实际 PTS 帧率、B 帧、解码错误 |
| `open_receiver.py` / `close_receiver.py` | 本机验收用 ffplay 窗口及自有 PID 管理；日常用户使用根目录接收脚本 |

### 5.4 tests/：测试证明什么

| 文件 | 检查内容 |
|---|---|
| `core_tests.cpp` | plane 边界/offset/stride、池归还、队列满、关闭唤醒、并发乱序保护、NMS |
| `capture_tests.cpp` | 对生产 Capture 注入模拟系统调用，覆盖 NV12/NV12M、超时、错误帧、部分 mmap 清理；不是实摄像头证明 |
| `mock_rknn.cpp` | 明确的假 RKNN runtime，仅供适配层测试；绝不部署为实际 NPU 推理库 |
| `model_tests.cpp` | 使用假 runtime 验证 CLIP 生命周期、9 context、有效类别、输出释放、绑核失败清理 |
| `picture_parity.cpp` | 在真实 RKNN 上对照单 context 与 9 context 并发图片结果 |
| `io_smoke.cpp` | 真实 RGA 的颜色/letterbox；可选取帧探针并不代表完整检测 |
| `nut_fixture.cpp` | 生成不均匀 PTS 的测试帧，验证时间戳没有被固定帧率改写 |
| `output_failure_tests.cpp` | tee 参数/编码只执行一次、非法分隔符、EPIPE、编码退出、背压超时、正常退出完整包 |
| `test_monitor.py` | CPU/帧计数差分、计数重置、NPU 不可用、/proc 字段解析、日志 PID 匹配/半行、CSV 列稳定 |

根目录 `.gitignore` 排除模型/运行产物，`.dockerignore` 排除构建上下文的大文件，`.gitattributes` 固定 Linux 脚本/配置为 LF，`.clang-format` 统一 C++ 排版。这些是工具配置，不是额外应用。

## 6. 如何改参数和检测类别

修改**板端** `/userdata/rk-yoloworld/config.env` 后，下次运行生效。修改电脑源码目录中的同名文件只会影响下次部署，不会自动改变正在运行的板端程序。

| 参数 | 当前值 | 作用 |
|---|---|---|
| `DEVICE` | `/dev/video44` | con7 对应 ISP 输出节点 |
| `WIDTH/HEIGHT` | `2560/1440` | ISP 输出尺寸，驱动返回不同尺寸会拒绝运行 |
| `FPS` | `60` | 采集请求和输出上限，不是检测结果保证值 |
| `BUFFERS` | `3` | 请求 mmap 数量，允许 2～32；日志另报实际数量 |
| `SKIP` | `5` | 跳过开头有效帧，避免 ISP 启动残留 |
| `CAPTURE_PRIORITY` | `0` | 普通线程调度；非零需要权限，本板盲目提升没有改善缺口 |
| `BITRATE` | `40000000` | H.264 CBR 目标 bit/s，不等于实测网卡流量 |
| `GOP` | `10` | 按实际编码帧数计的关键帧间隔，B 帧为 0 |
| `DESTINATION` | `udp://192.168.2.165:1235?pkt_size=1316` | 电脑 IP、端口、单 UDP TS 负载上限；启用 tee 时不允许 `|[]` 等保留分隔符 |
| `FFMPEG/FFMPEG_LIB` | 原项目私有运行路径 | 具备 rkmpp 硬编/硬解的 FFmpeg 与独立库搜索路径，不覆盖系统 FFmpeg |

修改 `model/detect_classes.txt`：每行一个英文类别/短语，当前模型允许 1～80 个有效类别。重启后 CLIP 只为这些类别生成一次缓存；未使用类别槽填零并被后处理屏蔽。少写类别不会自动缩小模型网络的计算量。

换 `.rknn` 时必须同时核对图像尺寸/布局、文本维度/容量、输出头、量化参数和 runtime/驱动兼容性。当前模型输入为图像 `[1,640,640,3]`、文本 `[1,80,512]`，CLIP 输入 `[1,20] INT64`，不是任意 YOLO 模型都可直接替换。

## 7. 普通启动、日志和异常恢复

**板端 Linux，目录 `/userdata/rk-yoloworld`：**

```bash
bash ./run_realtime_yolo_world.sh --probe
```

含义：检查文件、私有硬编 FFmpeg、CLIP、9 个独立绑核 context 与 RGA，不打开摄像头。优化版在本板准备 80 类通常为数秒，具体看启动日志。不会回退到 CPU 模型推理或软件编码。

**仍在这个板端目录，且摄像头已经空闲时：**

```bash
bash ./run_realtime_yolo_world.sh
```

含义：直接运行 C++ 检测，直到 Ctrl+C；普通入口发现摄像头占用时报告 PID，不自动结束其他进程。它不会保存/恢复旧视频，也不自动开 HDMI，所以本板已有原直播时优先用第 2 节的包装器。

启动脚本内部包含必需的库设置（这是脚本内容，日常不用单独再敲）：

```bash
export LD_LIBRARY_PATH=./lib:${LD_LIBRARY_PATH:-}
```

含义：当前检测进程优先使用私有 RKNN/RGA/NUT 库，保留原库路径。编码子进程会移除该路径和 `LD_PRELOAD`，单独使用 `FFMPEG_LIB`；HDMI 解码也使用原视频私有库，避免库串用。

包装器把每秒统计写到 `logs/时间.jsonl`，初始化/错误写到同名 `.log`；HDMI 日志为 `logs/detection-hdmi.log`；CSV 是监测工具按需生成的文件。普通直接启动默认把 JSON 发到终端，未保存 JSONL 时监测工具仍能显示 /proc 资源，但 FPS 可能“不可用”。

**板端 Linux，目录 `/userdata/rk-yoloworld`，在确认检测进程已经退出后：**

```bash
python3 tools/run_with_restore.py --restore-only
```

含义：异常断电、包装器被强制结束等情况后，读取 `state/before-test.json` 恢复原配置和 HDMI，并恢复本工具自己的调度日志。不运行检测、不刷镜像；不要在检测仍占用相机时执行。

| 现象 | 排查方向 |
|---|---|
| `Camera busy` | 原直播仍占相机；用有恢复保护的包装器，不同时开两个采集进程 |
| 电脑黑屏 | 核对板端 `DESTINATION`、电脑 IP/端口、ffplay 防火墙权限；重新开始一次检测时重开 ffplay，避免旧 PTS 基线 |
| 板端没有检测窗口 | 确认启动带 `--hdmi`、桌面已登录、DISPLAY/Xauthority 可用；查 HDMI 日志；不需要另开相机软件 |
| NPU 负载不可用 | 用有 debugfs 读取权限的账户；当前默认 root；缺值不代表 NPU 空闲 |
| 线程 FPS 第一秒无值 | 差分需要两份不同采样；继续等下一秒 |
| 监测显示“已过期” | 日志超过 3 秒或 PID 不符；检查检测是否退出/卡住，不能继续用旧采样判断性能 |
| 推理约 40、输出约 23 | 多线程乱序结果和队列取最新策略的差异；不是网络播放器必然丢了 17 帧 |
| driver gaps 增加 | 驱动 sequence 不连续；与主动队列丢弃、UDP 丢包分别排查，本版仍保留此限制 |
| 改电脑 `config.env` 板端无变化 | 需要重新部署该配置或直接改板端文件，并重启检测 |

## 8. 统计字段的完整口径

| JSON 字段 | 含义 |
|---|---|
| `pid/elapsed_s` | 当前检测 PID、视频阶段单调运行秒数 |
| `capture_fps/rga_fps/infer_fps/output_fps` | 成功取帧/完成预处理/完成推理/写完带框输出的计数增量除以实际时间 |
| `capture_total/infer_total/output_total` | 累计完成次数；取帧计数包含主动跳过的最初 5 个有效帧 |
| `driver_gaps/steady_driver_gaps` | 跳过启动帧后按驱动 sequence 统计的缺口，不会因为丢旧任务而增加 |
| `startup_driver_gaps/driver_gaps_total/driver_resets` | 启动跳变/包含启动的原始缺口/序号回退或重置 |
| `raw_drops/prepared_drops` | 两个有界队列的主动丢旧等待任务数 |
| `stale_results` | 晚到、序号已旧的结果被拒绝 |
| `result_replaced/output_replaced` | 槽里未消费的结果被更新结果替换 |
| `pool_drops/pts_drops/timeouts` | 池耗尽、非递增采集 PTS、采集超时 |
| `age_p50_ms/age_p95_ms` | 最近 4096 份有效输出从采集时间到管道写完的帧龄；不含网络/电脑解码/显示 |
| `age_all_*` | 本次运行累计帧龄直方图分位数，0.5 ms 粒度，5000.5 ms 为溢出桶 |
| `rga_*/infer_*` | 最近样本的预处理/推理调用耗时分位数；推理调用包含排队等待及该适配层后处理，不是纯 NPU 内核执行时间 |
| `cpu_core_percent/rss_mib/npu` | C++ 自身 CPU 差分、RSS 和驱动 NPU 文本；监测工具另外读取同类资源数据 |
| `workers` | 每个 worker 的编号、真实 Linux TID、NPU core 和累计完成数；用于监测，不暴露可变 context 指针 |

## 9. 编译、部署和交付文件

日常只修改正式工程的 `src/` / `include/`。修改后需要重新编译 ARM64、部署新程序；不能拿 Windows Python 直接执行 C++ 文件。

**Windows PowerShell，正式 `rk-yoloworld` 目录：**

```powershell
python tools\prepare_sources.py
```

含义：下载/验证锁定依赖，准备 tokenizer、SDK 头文件、RGA/FFmpeg 源码；不运行摄像头。

```powershell
python tools\import_deploy.py .\inputs\original_deploy
```

含义：从已经归档到 `inputs/original_deploy` 的原始部署目录导入模型和 runtime；也可以把最后一个参数换成自己的 `deploy.zip`。不运行原包 demo，不覆盖已选择的实测 RGA。

```powershell
docker build -f tools/Dockerfile -t rk-yoloworld-builder .
```

含义：`-f` 指定 Dockerfile，`-t` 为本地镜像取名，最后 `.` 是当前工程构建上下文；使用 Ubuntu 20.04 用户态工具链匹配板端 GLIBC 2.31。

```powershell
docker run --rm --mount "type=bind,source=$($PWD.Path),target=/project" rk-yoloworld-builder
```

含义：把当前目录挂到容器 `/project`，执行默认编译；`--rm` 只在容器结束后移除这个临时容器，电脑源码和 `build/dist` 输出保留。交叉编译采用 `aarch64-linux-gnu-gcc/g++`，并行数 4，显式启用 `-O3 -DNDEBUG`。

已有 Linux 交叉编译环境时，**Linux 主机/容器、工程根目录**：

```bash
bash tools/build_linux.sh
```

含义：验证依赖、构建仅 NUT 用途的私有共享库并编译 ARM64 程序；可通过 `CROSS_PREFIX` 指定兼容工具链前缀。不要使用要求 GLIBC 2.33 的 BSP 用户态库部署到当前 2.31 板子。

**Windows PowerShell，正式工程目录：**

```powershell
python tools\package_release.py
```

含义：生成 `dist/rk-yoloworld-source.zip` 和 `dist/rk-yoloworld-EVM3588-arm64.zip`；后者含可执行文件、模型、私有库、运行/监测工具、文档和对应源码 ZIP。原大型硬编 FFmpeg 复用板端 `/userdata/av_dev/ffmpeg_pipeline`，包中不重复分发。

```powershell
python tools\verify_release.py
```

含义：检查 ZIP 完整性、源码和 ELF 对应关系、清单与 SHA-256；更新源码后应重新构建再打包。

把部署 ZIP 传到板端 `/userdata/` 后，**板端 Linux**：

```bash
unzip -n /userdata/rk-yoloworld-EVM3588-arm64.zip -d /userdata/yoloworld-release
```

含义：`-d` 指定新目录，`-n` 不覆盖已有文件；每次升级用新的目标目录，不覆盖正在运行的程序。

```bash
cd /userdata/yoloworld-release/rk-yoloworld
```

含义：进入新解压的运行目录。其工具自动以自身所在目录为根，不要求再复制一份到旧目录。

```bash
chmod +x ./rknn_yolo_world_realtime ./run_realtime_yolo_world.sh
```

含义：给可执行文件和脚本增加执行权限，然后在新目录按第 7 节运行 probe，按第 2 节运行带恢复的检测。

主机监测测试可在**Windows PowerShell、工程目录**执行：

```powershell
python -m unittest discover -s tests -p test_monitor.py -v
```

含义：Python 内置 unittest 查找 `tests/test_monitor.py`，`-v` 显示各项结果；不访问摄像头或 NPU。

## 10. 实测结论与下一步

上一版“电脑单路预览”的真实相机 30 分钟基线：采集 **59.25 fps**、9 context 合计推理 **41.76 fps**、有效带框输出 **22.98 fps**；检测进程 CPU **199.86%**，RSS **515.10→520.30 MiB**，运行阶段仍有 **1348 个驱动序号缺口**。这是基线版本和该配置的结果，不是新双端显示模式保证值。

本轮新增了独立 worker/TID 计数、终端资源监测、可选检测 HDMI 和同一次硬编双输出；已重新编译并进行独立回归，用户已确认两端画面和目标框正常。开启 HDMI 会增加 RGA、VPU、CPU 和内存负载，性能需看该模式的独立记录，不能沿用单路基线当成新模式长测结论。

完整记录见 [VALIDATION.md](VALIDATION.md)，实施进度见 [todo.md](todo.md)，第三方固定来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。后续优先分析驱动序号缺口、9 context 的乱序损耗与后处理 CPU 开销，再考虑把 `monitor.py --json` 的数据接入现有上位机。当前没有实现每 context 的精确 NPU 百分比、中文画面字库、模型转换、ROI 或曝光控制。

实现依据与数据定义可核对：[FFmpeg tee 官方说明](https://ffmpeg.org/ffmpeg-formats.html#tee)、[ffplay 官方说明](https://ffmpeg.org/ffplay.html)、[Linux /proc 官方说明](https://www.kernel.org/doc/html/latest/filesystems/proc.html)。这些资料解释接口与统计口径，实机性能以本项目自己的验收记录为准。
