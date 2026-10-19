# IMX415 / EVM3588 B1 实验性 4K60 BSP

2026-10-19：已按用户授权仅更新 boot 并启动实验内核。真实相机、H.265 硬编、板端硬解的 30 分钟测试均约 59.99 fps；电脑端完整长测按用户安排后续进行。最新状态见 [构建与实测清单](build-validation.json) 和 [验收记录](../../../docs/history/4K60与性能监测验收.md)。普通部署不包含 BSP，桌面按钮不会刷写内核。

## 模块与数据流

IMX415 RAW10 → CSI/ISP → /dev/video44 NV12M → FFmpeg hevc_rkmpp → MediaMTX，分别供板端硬解/HDMI、电脑 RTSP/Qt 读取。只有 FFmpeg 一个进程采集相机，MP4 录像流复制。HDMI 当前为 1920×1080@60 Hz；完整解码输入为 3840×2160。

| 文件 | 职责 |
| --- | --- |
| `0001-experimental-mode.patch` | 增加完整 60 fps 传感器寄存器模式 |
| `candidate.json` | SDK 驱动与参考补丁版本/哈希；源码生成阶段记录 |
| `evm3588-b1-4k60.dts` | 独立构建用设备树，给 con7 传感器添加实验开关 |
| `build_candidate.sh` | 专用目录内编译，最多 4 个任务，不刷写 |
| `build-validation.json` | 实际 Image、FIT、分区镜像哈希和验收状态 |
| `probe.py` | 只读实机信息 |
| `switch_boot.py`、`tests/` | 本板限定的 boot 写入/回退保护及普通文件测试；默认只检查 |
| `tools/dev/prepare_boot_candidate.py`（项目根目录） | 修补实际 B1 resource DTB，更新校验并重封装 FIT |

## 驱动改动

基于厂商 SDK Linux 5.10.110 内建 IMX415 驱动。新增完整 RAW10 3864×2192 线性模式，HMAX 528、VMAX 2344、37.125 MHz XVCLK，以及 D-PHY、曝光、HTS/VTS 等寄存器。没有复制帧、插帧或仅修改帧率声明。

仅 con7 节点 `/i2c@feaa0000/imx415@36` 含 `dvsense,experimental-4k60` 时启用，同时设置 `rockchip,camera-hdr-mode=0`，固定 NO_HDR，避免 AIQ 协商退回旧模式；拒绝 HDR 切换。其它相机和旧模式保留。

寄存器参考 [bambooCZ 固定提交](https://github.com/bambooCZ/rk3588-imx415-4k60/tree/a779a49f70a7cd3b3732366d02c76f4b48f5a9d4)，保留 Rockchip/原作者版权及 GPL-2.0。参考项目针对另一款板和 6.1 BSP，本工程适配至厂商 5.10；不能推广为任意模组通用固件。传感器配置为 1485 Mbit/s/条，按参考向接收器报告 1520 Mbit/s 触发校准；这不是仪器实测速率。

## boot 封装修正与实测

首版仅改 FIT 主 DTB，新内核成功启动但相机仍为 30 fps。诊断发现 resource 内另有多份板型设备树。本板 ADC5 实测 3751，U-Boot 选择 `evm3588#_saradc_ch5=3754.dtb`，其 model 为 B1；主 DTB 中的实验属性没有进入运行中的设备树。

首版已回退至原 boot，整分区 SHA-256 和原内核重启均验证通过。随后在同一 boot-only 授权范围修正封装：只给 B1 resource DTB 增加上述两项属性，主 FIT DTB 也采用相同 B1 DTB，更新 resource 内 SHA-1 和 FIT SHA-256。其它板型 DTB、logo、initramfs 原样保留；内核与首版一致。

修正版运行 DT 属性、驱动 60 fps 模式、180 帧直接采集约 59.99 fps 均已确认。真实画面 USB 短测 60 秒：采集 60.02、编码 60.00、板端硬解 59.99、电脑解码 59.98、Qt 绘制 59.79 fps。用户确认 HDMI 颜色正常且持续更新。短测不能替代有线网络 30 分钟验收。

板端连续 1800.391 秒、1798 个采样：采集 59.994、编码 59.991、硬解 59.994 fps，平均 RTSP 流速 20.243 Mbit/s；最高温度 59.153°C。新增 1 个驱动编号缺口，日志对应一次 CIF 缓冲未就绪；采集错帧、编码丢帧和补帧计数为 0。达到平均 ≥59 fps 目标，不声称零丢帧。

修复电脑性能模式解码线程后，局域网前台 60 秒解码 59.964、Qt 绘制 58.404 fps，首帧 1.375 秒，无重连、预热后无新增解码错误。电脑独立解码 941.984 秒约 59.992 fps 后按用户要求停止；它不是 30 分钟验收。

清单中 `realCamera4k60CaptureValidated` / `boardPipeline4k60Validated` 表示板端达标；`realCamera4k60Validated` / `fullChain4k60Validated` 仍为 false，表示完整电脑长测、零新增缺口等条件尚未完成。它不阻止按真实模式请求 60 fps。`candidate.json` 和打包的 `fit-manifest.json` 是生成阶段记录，实际状态看 `build-validation.json`。

| 对象 | SHA-256 |
| --- | --- |
| 原始 64 MiB boot | `7cf5378f68e374aec8d2fe8b01e8ba4e8e36863a8b71f61ba670c5f6dc3bca7f` |
| 修正版 FIT，50,827,264 字节 | `9c35ccb2a09535277340fe81ad351d624f346b67bb9a96f577bfa1a6329f66b0` |
| 实际写入的补零 64 MiB boot | `102a8af58b9bc0b6a5d542db4c41ca99b2dc0f4586776b67e78332836c1147c9` |
| 内核 Image | `edf63ba908f885c6e7c9cd7046629b489a026678bfa6a8cb60ff8e4c283625ec` |
| B1 DTB | `57abfe6b480b7d924961615e5fb612ed047c4ec5f6021d4b4b218ad985e1e2eb` |
| 保持不变的 U-Boot | `7afde1f520b04124370c3dc7a4729a615f6ff85e4f1ff36ad63ac2a50877f84a` |

旧 `BSP-CANDIDATE-20261016.zip` 只有首版封装，不再用于启用本板 60 fps。最新本地试验包为 `releases/EVM3588-IMX415-4K60-BSP-TRIAL-20261019.zip`。源码包不包含镜像。

## 可重复构建

**Windows PowerShell，av_dev 根目录：**

```powershell
.\.venv-desktop\Scripts\python.exe .\tools\dev\prepare_imx415_candidate.py --sdk '..\Linux\SDK&Image\SDK\evm3588_linux_rkr3.3-v1.0.3_v1.2.1.23_sdk.tar.gz'
```

解释：只读取 SDK 驱动，校验固定参考补丁并生成差异补丁。`--sdk` 指定 SDK；文件虽然名为 `.tar.gz`，实际为未压缩 TAR，工具会识别。不展开整个 SDK，不刷写开发板。

**隔离 Linux 构建环境，路径按实际挂载调整：**

```bash
LIVE_CONFIG=/evidence/config-5.10.110 CROSS_COMPILE=/toolchain/bin/aarch64-none-linux-gnu- bash /project/board/bsp/imx415-4k60/build_candidate.sh /sdk/evm3588_linux_rkr3.3-v1.0.3_v1.2.1.23_sdk.tar.gz /work/candidate --image
```

解释：`LIVE_CONFIG` 是原板端备份配置，`CROSS_COMPILE` 是同版本厂商 GCC 10.3 前缀；两个位置参数是只读 SDK 和专用构建目录，`--image` 编译 Image/DTB。最多 4 个任务，本次 CONFIG_* 与原系统零差异。Image 还需 FIT 封装，不能直接写入 boot。

```bash
python3 /project/tools/dev/prepare_boot_candidate.py --original /evidence/boot-original.img --original-sha256 7cf5378f68e374aec8d2fe8b01e8ba4e8e36863a8b71f61ba670c5f6dc3bca7f --kernel /work/candidate/out/arch/arm64/boot/Image --output /evidence/fit-candidate-b1-v2
```

解释：校验 `--original` 原 boot 的哈希，提取 B1 DTB，以 fdtput 加入实验属性、mkimage 重封装；`--kernel` 指定已编译 Image，`--output` 指定普通输出目录。保留地址/version/对齐，验证 resource 每个文件和 FIT 全部载荷，不打开块设备。重新生成需重新核对最终哈希，构建时间不同可能改变 FIT 字节。

## 回退与恢复入口

唯一更新目标为 `/dev/mmcblk0p3`，标签 boot，LBA `0x8000`，`0x20000` 个 512 字节扇区，64 MiB。没有 boot_a/boot_b，也没有失败自动切槽。原备份在板端 `/userdata/av_dev_backups/boot-pre-4k60-20261016.img`，电脑副本在相邻 `av_dev_archive_20261016/performance-20261016/boot-original.img`，不入 Git。

已验证：按住正确的 SW2，断开 12V、确认灯灭，保持按住并重新接上 12V，可独立于 Linux 进入 Maskrom。USB-C 保持连接，RKDevTool 2.96 识别后松开 SW2。SW4/Loader 冷启动入口仍未通过，不作为回退保障。

官方固件提取的升级 Loader 为 471,488 字节，SHA-256 `8ae556b82e89b55115894275a8a5ac2181b18e86c4f887e654491bcbcd085868`。通过“高级功能 → Boot → 下载”只加载到 RAM，成功读取三星 eMMC/GPT 并返回原系统。运行内存 Loader 后工具仍可能显示 MASKROM，以真实 FlashInfo/GPT 读取结果为准。没有写入 Loader、U-Boot 或 GPT，也没有演练 Maskrom 分区写回。

Linux 内恢复原 boot 已实际执行、整分区校验并重启通过。`switch_boot.py` 默认只检查板型、目标范围、原备份/候选哈希及 U-Boot；写入前要求直播、录像停止。写后 fsync、刷新块缓存、读回整分区，不自动重启；不能提供断电情况下的自动回退。

**开发板 Bash，仅在需要回退时依次执行：**

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py stop
```

解释：停止本项目直播、硬解和录像，有录像时先正常封口。

```bash
python3 /userdata/av_dev/firmware_candidates/20261019-b1-v2/switch_boot.py --restore-original
```

解释：`--restore-original` 只把已锁定原备份写回上述 boot 并读回全部 64 MiB 校验；不改其它分区。仅在输出 `ok:true` 且 `afterSha256` 为表中原 boot 哈希时继续。

```bash
systemctl reboot
```

解释：正常重启，使已校验原 boot 生效；会中断连接与画面。返回后确认原内核 `#6 SMP Mon Sep 11 10:30:50 CST 2023`。

恢复原内核后，如需普通预览，先在软件里把已保存参数改回 H.265、1920×1080、30 fps、2.5 Mbit/s、GOP 30 再启动，避免沿用实验系统的 60 fps 请求。原驱动会拒绝无法支持的高帧率。

若 Linux 无法启动：使用上述 SW2 冷启动入口、官方 Loader 仅内存加载，读取实际分区表，核对 boot 地址/容量，只将原始 64 MiB boot 写回该分区。不要执行整机升级或擦除。完整恢复日志、原始镜像及本次试验留在电脑外部归档 `recovery-rehearsal/`。
