# 本地交付物

- `EVM3588CameraConsole-Windows-x64-v1.2.0.zip`：性能监测版免安装桌面包，含 FFmpeg。
- `EVM3588-IMX415-4K60-BSP-CANDIDATE-20261016.zip`：未刷写、未实机启动验证的实验 FIT/DTB/补丁与校验清单，不能视为已通过的固件。
- `EVM3588CameraConsole-Windows-x64-v1.1.0.zip`：保留的上一版桌面包。
- 同名 `.zip.sha256`：对应校验值。
- `av_dev-source.zip`：运行源码打包工具后生成。
- `desktop/1.2.0/`：已构建的免安装目录。

这些产物不入 Git，只有本说明入库。修改源码不会自动更新已有 EXE。1.2.0 的测试范围见 [验收记录](../docs/history/4K60与性能监测验收.md)；真实相机 4K60 仍待实验内核切换和实测。原 boot 与程序备份在板端及 av_dev 外部归档，不能把候选镜像当作原固件备份。
