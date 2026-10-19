# 本地交付物

- `EVM3588CameraConsole-Windows-x64-v1.2.2.zip`：当前免安装桌面包，含 FFmpeg；自适应分栏、窄屏换行、长路径显示与采集缓冲诊断。
- `EVM3588CameraConsole-Windows-x64-v1.2.1.zip`：上一版桌面包。
- `EVM3588-IMX415-4K60-BSP-TRIAL-20261019.zip`：原始 boot 试验镜像、B1 resource 封装修正及回退工具；镜像未变，包内记录截止首次打包，后续电脑长测与缺口结果以当前验收文档为准。
- `EVM3588CameraConsole-Windows-x64-v1.2.0.zip`、`v1.1.0.zip`：旧版桌面包。
- `EVM3588-IMX415-4K60-BSP-CANDIDATE-20261016.zip`：历史首版封装，实测未启用 B1 的 60 fps 模式，已被新试验包替代，不再用于启用 4K60。
- 同名 `.zip.sha256`：对应校验值。
- `av_dev-source.zip`：运行源码打包工具后生成。
- `desktop/1.2.2/`：当前免安装目录；旧版本仍在各自子目录。

这些产物不入 Git，只有本说明入库。修改源码不会自动更新已有 EXE。最新启动及真实 4K60 验证范围见 [验收记录](../docs/history/4K60与性能监测验收.md)。原 boot 和程序备份在板端及 av_dev 外部归档；试验镜像不能代替原固件备份，普通桌面部署不刷写 BSP。
