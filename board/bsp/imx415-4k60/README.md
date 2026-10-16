# IMX415 / EVM3588 B1 实验性 4K60 BSP

这里是 **未在开发板启动验证的候选适配**。它不属于普通部署，不会被 `tools/deploy/deploy.ps1` 上传或应用。当前相机仍是 20/30 fps 驱动，不能据此声明完成真实 4K60。

## 已完成的适配

- 匹配本地厂商 SDK 的 `kernel/drivers/media/i2c/imx415.c`，源文件 SHA-256 锁定于 `candidate.json`。SDK 为 Linux 5.10.110，驱动内建。
- 新增完整 RAW10 3864×2192 线性模式和寄存器表，涉及 HMAX/VMAX、SYS_MODE、输入时钟选择、D-PHY 时序、曝光默认值、HTS/VTS 和链路频率菜单。
- 保留旧模式，默认不启用实验模式。仅传感器设备树带 `dvsense,experimental-4k60` 时启用，固定线性模式，防止 AIQ 的 NO_HDR 协商退回旧 30 fps；拒绝 HDR 切换。
- 单独的 `evm3588-b1-4k60.dts` 继承原 B1 设备树，只给 con7 对应的 `imx415_1` 添加实验属性，保留四条 CSI 数据线和已有硬件拓扑。
- Linux Docker 内交叉编译，不写开发板 `/boot`。构建结果和最终校验值见本地发布物及验收记录。

本轮已完成同版本 GCC 10.3 与实际板端内核配置构建，`CONFIG_*` 对比为零差异；已按原 boot 的 FIT 封装生成候选启动镜像。主 DTB 直接取自原 boot，仅增加实验属性与线性 HDR 配置，initramfs/resource 原样保留。详见 [构建校验清单](build-validation.json)。`candidate.json` 记录源码生成阶段，实际编译状态以该校验清单为准。**没有刷写或重启验证；恢复启动方法尚未实际演练，因此当前交付不能当作已通过的固件。**

本地候选包为 `releases/EVM3588-IMX415-4K60-BSP-CANDIDATE-20261016.zip`。原始 64 MiB boot 分区已备份到板端 `/userdata/av_dev_backups/boot-pre-4k60-20261016.img`，并在电脑相邻 `av_dev_archive_20261016/performance-20261016/` 留一份；原始 boot SHA-256 为 `7cf5378f68e374aec8d2fe8b01e8ba4e8e36863a8b71f61ba670c5f6dc3bca7f`。这些二进制备份不上传 GitHub。

寄存器方案来自 [bambooCZ/rk3588-imx415-4k60 固定提交](https://github.com/bambooCZ/rk3588-imx415-4k60/tree/a779a49f70a7cd3b3732366d02c76f4b48f5a9d4)，原项目 GPL-2.0，作者 Miloslav Mrvík，底层驱动版权属于 Rockchip。参考补丁的哈希也固定。原作者在另一款板和 6.1 BSP 验证过；**不代表当前 EVM3588 的 CSI 校准、ISP 或模组已验证**。适配保留原驱动版权，许可证见本目录。

候选模式使用 37.125 MHz XVCLK、1485 Mbit/s/条传感器链路，按参考方案向接收器报告 1520 Mbit/s 触发校准。这个差异是待实测的接收器兼容处理，不能解释为已经测得的链路速率。HMAX 528、VMAX 2344，增加垂直消隐；仍须检查 CSI CRC、ISP 丢帧、时间戳与真实运动画面，不能仅看帧率声明。

[Rockchip Toybrick 的 5.10 参考](https://t.rock-chips.com/forum.php?mod=viewthread&tid=4827)有另一套 1782 Mbit/s 模式，但附件需要登录，本轮没有获得或假造该寄存器表。

## 可重复生成

**Windows PowerShell，av_dev 根目录：**

```powershell
.\.venv-desktop\Scripts\python.exe .\tools\dev\prepare_imx415_candidate.py --sdk '..\Linux\SDK&Image\SDK\evm3588_linux_rkr3.3-v1.0.3_v1.2.1.23_sdk.tar.gz'
```

解释：从本地 SDK 只读取驱动，下载并校验固定参考补丁，生成差异补丁和锁定清单。`--sdk` 是 SDK 路径，注意文件虽然名为 `.tar.gz`，实际是未压缩 TAR；程序会识别。不会展开整个 SDK 或改动原 SDK。已下载参考时可加 `--reference` 指定本地补丁。

**隔离的 Linux 构建环境：**

```bash
bash /project/board/bsp/imx415-4k60/build_candidate.sh /sdk/evm3588_linux_rkr3.3-v1.0.3_v1.2.1.23_sdk.tar.gz /work/candidate
```

解释：第一个路径是只读 SDK 压缩包，第二个是专用绝对构建目录。解出内核，校验源文件，应用补丁，以 SDK 配置编译 IMX415 ARM64 对象；最多 4 个任务。只影响该构建目录。

```bash
LIVE_CONFIG=/evidence/config-5.10.110 CROSS_COMPILE=/toolchain/bin/aarch64-none-linux-gnu- bash /project/board/bsp/imx415-4k60/build_candidate.sh /sdk/evm3588_linux_rkr3.3-v1.0.3_v1.2.1.23_sdk.tar.gz /work/candidate --image
```

解释：`LIVE_CONFIG` 选择从实际开发板备份的内核配置；`CROSS_COMPILE` 选择厂商同版本 GCC 10.3-2021.07 的前缀；`--image` 再构建 Linux `Image` 与独立实验 DTB。这里的路径是构建环境示例，需按实际挂载修改。`Image` 不是可直接覆盖板端 boot 分区的成品镜像；脚本从不刷写或重启。

## 系统切换前必须完成

1. 使用 `probe.py` 读取实际板型、内核、时钟、传感器模式、启动参数、分区及 `/boot` 校验值，保存到本地；运行过程中不设寄存器、不启停采集。
2. 对比候选与实际内核配置、DTB、GCC、模块 ABI 和启动镜像封装。不能仅因 `uname` 同为 5.10.110 就判定完全匹配。
3. 备份实际 boot 分区、DTB、内核配置和依赖模块；拷贝到电脑并核对哈希。准备同板型官方恢复固件和已验证的恢复接口。当前源代码/FFmpeg 备份不是完整固件备份。
4. 在完整启动封装、原始分区备份、回退方法都可审阅后，再由用户单独确认系统切换。当前没有授权自动刷写，普通桌面按钮也不会执行内核操作。
5. 首次启动先短测；确认枚举 60 fps、采集约 60 个不同运动帧/秒、无重复 PTS、CSI/ISP 无持续错误，再做 30 分钟真实链路验收。失败恢复原 boot/DTB/模块，并恢复 1080p30 默认直播。

`tools/dev/prepare_boot_candidate.py` 在隔离 Linux 中使用官方 `fdtput`、U-Boot `mkimage` 封装。它只接受校验值匹配的原 boot 普通文件，校验原图像各载荷哈希，保留原地址、Rockchip version/totalsize 和外部数据对齐，再校验候选全部载荷与分区容量。该脚本没有块设备写入接口；候选 ITS 供审阅，重新封装需要原 boot 备份和对应候选内核，不是直接在压缩包里运行 ITS。

**当前不存在一个已经实机验证的自动刷写或回退命令。** 为避免把不同系统的 boot 分区或挂载方式混用，这里没有给出未经当前板验证的 `dd` / 刷机命令。候选材料、固件回退准备与真实 4K60 测试分别报告。
