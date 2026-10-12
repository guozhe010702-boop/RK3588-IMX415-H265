# EVM3588-B / IMX415 / MPP H.265

IMX415 接 con7，RKISP `/dev/video44` 采集。项目包含已经实测的 HDMI + H.265 TCP 预览脚本，以及用于学习 V4L2 与 MPP C API 的两个文件编码程序。

先阅读 [路线二：操作、程序解释与修改指南](docs/路线二_MPP_C_API_操作与修改指南.md)。每条操作命令均标明电脑 PowerShell 或板端 Bash，并解释参数。

| 内容 | 入口 |
| --- | --- |
| 方案网页 | [EVM3588-B_音视频实时压缩方案.html](EVM3588-B_音视频实时压缩方案.html)，下载后在本地浏览器打开 |
| Windows 部署 | [deploy.ps1](deploy.ps1) |
| HDMI + H.265 TCP | [board/07_h265_preview_tcp.sh](board/07_h265_preview_tcp.sh) |
| 共用 MPP H.265 引擎 | [board/v4l2_mpp_enc/mpp_h265.c](board/v4l2_mpp_enc/mpp_h265.c) |
| 无摄像头文件编码 | [board/v4l2_mpp_enc/yuv_mpp_enc.c](board/v4l2_mpp_enc/yuv_mpp_enc.c) |
| IMX415 双平面取帧 | [board/v4l2_mpp_enc/v4l2_mpp_enc.c](board/v4l2_mpp_enc/v4l2_mpp_enc.c) |
| 板端构建 | [board/v4l2_mpp_enc/Makefile](board/v4l2_mpp_enc/Makefile) |
| 网页状态采样 | [refresh_status.ps1](refresh_status.ps1)；[board_status.example.js](board_status.example.js) 是空状态模板 |

## 操作入口

电脑 PowerShell，在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy.ps1 -BuildExamples
```

`powershell.exe` 启动子进程；`-NoProfile` 不加载个人配置；`-ExecutionPolicy Bypass` 对这次运行放行脚本；`-File` 指定入口；`-BuildExamples` 上传后在板端编译两个 C 程序。需要时加 `-AdbPath`，后面接本机 adb.exe 的完整路径。部署不会停止当前实时画面；C 源码位于板端 `/userdata/av_dev/mpp_route2/`。

开发板 Bash，在摄像头空闲后执行：

```bash
cd /userdata/av_dev/mpp_route2
```

`cd` 进入 C 项目的板端目录。

```bash
./v4l2_mpp_enc -d /dev/video44 -o new_capture.h265 -c h265 -w 1920 -h 1080 -b 4000000 -f 30 -n 60
```

`./v4l2_mpp_enc` 运行当前目录程序；`-d` 指定采集节点；`-o` 指定未使用的输出文件名；`-c` 指定 H.265；`-w/-h` 请求宽高；`-b` 是目标 bit/s；`-f` 配置帧率；`-n` 是帧数。这个 C 程序录完退出；它与 07 不能同时打开摄像头。完整的暂停、检查输出与恢复步骤见操作指南。

## 验证与边界

2026-10-12 在实际开发板验证：

- 板端 MPP 开发文件版本 `1.5.0-4ubuntu2.2firefly5`，两个 C 程序编译通过。
- NV12 文件 → 30 帧 640×360 HEVC；IMX415 → 60 帧 1920×1080 HEVC，均经 ffprobe 统计完整帧数。
- GStreamer 07 支持 HDMI 与电脑 ffplay 同时看画面，用户已确认两端正常。

C 程序当前输出裸 H.265 文件；运行时动态码率、ROI、自研网络输出、C HDMI 显示、零拷贝与音视频同步属于后续开发。短测试不代表已完成长期稳定性验证。

网页状态是本地采样快照，生成的 `board_status.js` 不入 Git。首次下载可以将 `board_status.example.js` 复制为 `board_status.js`，或运行状态采样脚本。SDK PDF 链接和 ZIP 下载链接在未配置对应本地资料时不可用；仓库不包含厂商 SDK 或本地交付 ZIP。

Git 跟踪根目录 `board/` 和项目说明；`音视频代码包/` 是本地交付副本。备份、SDK、录像、二进制、电脑缓存与运行状态由 `.gitignore` 排除。这个项目自己的源码未另行声明开源许可证。
