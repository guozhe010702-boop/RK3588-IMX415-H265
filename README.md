# RK3588 / IMX415 相机项目

**先读 [项目程序逻辑与目录导航](docs/项目程序逻辑与目录导航.md)。** 这份阅读地图说明每个目录、视频/控制/文件三条链路、按钮调用顺序、运行状态，以及修改功能应该定位哪个模块。

当前产品由 Windows 桌面控制台、板端 FFmpeg / RK3588 VPU 和 MediaMTX 组成。IMX415 接 EVM3588-B con7，经 `/dev/video44` NV12M 采集，H.265 硬编后通过 RTSP 同时提供 HDMI、电脑预览、手动 MP4 录像和 JPEG 截图。

默认 1920×1080、30 fps、H.265 CBR 2.5 Mbit/s、GOP 30、无音频。H.264 可在界面选择。MPP C API 与 GStreamer 方案保留用于学习和对照，当前产品不依次运行编号脚本。

## 按目的找入口

| 目的 | 入口 |
| --- | --- |
| 理解程序、目录和调用顺序 | [项目程序逻辑](docs/项目程序逻辑与目录导航.md) |
| 查看本次结构拆分和验证 | [结构整理记录](docs/项目结构整理记录.md) |
| 使用已发布的桌面软件 | [Windows 操作指南](docs/Windows_相机控制台操作指南.md) |
| 部署、构建和底层命令 | [FFmpeg 全链路指南](docs/FFmpeg_全链路操作指南.md) |
| 查看板端代码分类 | [board/README.md](board/README.md) |
| 查看桌面模块分类 | [desktop/README.md](desktop/README.md) |
| 学习 V4L2 / MPP C API | [路线二指南](docs/路线二_MPP_C_API_操作与修改指南.md) |
| 找其它设计、调研和历史验收 | [文档目录](docs/README.md) |
| 查看方案与手动采样状态 | [方案网页](EVM3588-B_音视频实时压缩方案.html) |

## 源码结构

```text
board/
  ffmpeg_pipeline/          当前板端产品
    avctl.py               稳定 CLI 入口
    camera_control/        配置、辅助函数、生命周期、服务通信、CLI 实现
    patches/               NV12M 采集兼容补丁
    tests/                 单元与硬件验收
  v4l2_mpp_enc/             MPP C API 学习代码
  00_...07_...sh            环境检查与原 GStreamer 方案
desktop/
  main.py                  Windows 应用入口
  evm_console/             界面布局、业务协调、SSH、视频、文件与本地回放
  tests/                   桌面单元与运行监测
docs/                      Markdown 编辑源、生成的 HTML、历史验收
tools/                     文档、交付和验证工具
deploy.ps1                 Windows 上传板端源码
refresh_status.ps1         Windows 生成网页状态快照
```

根目录 `board/`、`desktop/` 是修改源。`音视频代码包/` 和源码 ZIP 是生成副本；`desktop/dist/`、EXE ZIP 是构建产物。修改源码不会自动修改电脑 EXE 或板端运行实例。

## 当前交付与本次整理

已发布桌面包为本地 `EVM3588CameraConsole-Windows-x64-v1.1.0.zip`。完整解压后双击 EXE，首次连接填写自己的 SSH 密码或密钥；无需安装 Python。

本轮是源码结构重构：拆开板端 `avctl.py` 的多种职责，分离桌面布局与本地回放，统一代码排版并建立导航。**没有新增功能、重新发布 EXE 或覆盖开发板运行目录。** 原接口、动作名称与 JSON 调用方式继续使用。

后续需要部署新结构时，入口文件与 `camera_control/` 必须一起上传；`deploy.ps1` 已递归收集 Python 模块。本轮未执行部署。

## 最小命令入口

**开发板 Bash**，查询现有状态：

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py status
```

解释：`python3` 执行板端 CLI；`status` 查询常驻服务并返回 JSON，不重新打开摄像头。

**电脑 PowerShell，项目根目录**，上传源码时使用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1
```

解释：`powershell.exe` 启动子进程；`-NoProfile` 不加载个人配置；`-ExecutionPolicy Bypass` 仅对本次进程放行；`-File` 指定上传脚本。它不会自动编译或切换管线。其余命令与参数按用途查完整指南。

## 运行数据与备份

板端运行根目录为 `/userdata/av_dev/ffmpeg_pipeline/`。配置、私有库、状态、日志、MP4 和 JPEG 分目录存放；电脑个人配置在 `%LOCALAPPDATA%\EVM3588CameraConsole\`，保存的密码在 Windows 凭据管理器。

网页状态由 `refresh_status.ps1` 手动生成，页面显示采样时间；浏览器不直接控制 SSH 或播放 RTSP。真实凭据、媒体、运行快照、备份、SDK 和构建产物不上传 GitHub。

本轮备份为 `backups/before_structure_refactor_20261013/source.zip`，Git 标签为 `before-structure-refactor-20261013`。历史验收对应当时版本，不作为新结构的硬件部署验收；各轮记录见文档导航。上游组件许可证以各自源码为准，本项目未另行声明整体开源许可证。
