# Windows 上位机设计与开源调研

本轮交付设计与板端接口。Windows 桌面程序将在下一阶段实现；当前可运行的是 FFmpeg 硬编、RTSP、HDMI、录像、截图和 `avctl.py`。调研日期：2026-10-13。

## 1. 技术选择与开源参考

采用 Windows + PySide6 界面、Paramiko SSH/SFTP 控制、独立 FFmpeg 解码进程。视频经 RTSP 传输，SSH 只传控制与状态，SFTP 下载文件。

| 项目与原始资料 | 可以参考的内容 | 对本项目的适用范围 |
| --- | --- | --- |
| [BelEye](https://github.com/belkaniacode/BelEye)（MIT） | PySide6、FFmpeg 预览、重连、系统凭据存储 | 可参考视频模块；还需自行实现 RK3588 SSH 控制驱动 |
| [camera-control-desktop](https://github.com/dsvsergey/camera-control-desktop)（MIT） | 可插拔相机驱动、控制界面、RTSP 预览 | 现有 ONVIF/VISCA 面向 PTZ 相机；IMX415 MIPI 需要新的板端驱动适配 |
| [Paramiko](https://github.com/paramiko/paramiko) | Python SSHv2 与 SFTP | 后台控制与文件下载；核对主机指纹，避免每次点击重新登录 |
| [PyAV](https://github.com/PyAV-Org/PyAV) | FFmpeg 库的 Python 绑定 | 后续算法处理候选；首版先使用独立进程，便于限制解码故障影响 |
| [MediaMTX](https://github.com/bluenviron/mediamtx) | RTSP 分发、API 与客户端管理 | 板端已部署，首版沿用；管理 API 保持只监听本机 |

上述项目没有直接提供本开发板完整控制程序。首版应组合已有组件与本项目的 `avctl.py`，不需要重做编码器。若后续复制参考项目代码，保留其许可与版权声明；各依赖的实际发布版本、许可和二进制分发条件需在打包阶段记录。

## 2. 模块与线程安排

```text
PySide6 主线程：窗口、按钮、状态和最新画面
 ├─ SSH Worker：Paramiko 持久连接 → avctl JSON → 板端控制服务
 ├─ Video Worker：FFmpeg RTSP TCP → BGR24 → 最新帧队列（容量 1）
 └─ Download Worker：SFTP → 本地临时文件 → 校验后完成

板端：IMX415 → FFmpeg / RK3588 VPU → MediaMTX
                                    ├─ HDMI 播放
                                    ├─ Windows 预览
                                    └─ 手动 MP4 流复制录像
```

SSH、磁盘下载、解码读取均在后台执行。主线程只接收 Qt 信号，不等待网络。预览尺寸先以 1280 宽为上限，保持宽高比；原始直播和录像仍为 1920×1080。解码输出必须按完整帧长度组装，不能把一次管道读取当成一帧。消费慢时覆盖旧帧，禁止无限队列。

视频进程用参数列表启动，禁止拼接 shell 命令。分别消费 stdout 图像与 stderr 日志，避免日志管道塞满阻止解码。关闭窗口先停本地解码、取消下载、释放 SSH；不自动停止板端直播和录像。

## 3. 五个界面

| 页面 | 首版控件 | 显示与操作规则 |
| --- | --- | --- |
| 连接 | IP、SSH 端口、用户、密码或密钥、连接/断开 | 首次确认主机指纹；显示 SSH 与 RTSP 各自连接状态 |
| 视频 | 实时预览、启停直播、HDMI 开关、重连 | 展示实际编码器、帧率、丢帧和 VPU 状态；黑屏附具体原因 |
| 编码 | H.264/H.265、宽高、帧率、码率、GOP、应用 | 修改通过受控重启；录像中禁用应用并提示先停止录像 |
| 录像/截图 | 开始/停止、文件列表、下载、截图 | 录像完成需板端 MP4 验证通过；显示容量与下载进度 |
| 日志 | 模块筛选、刷新、复制错误 | 显示编码、RTSP、控制服务错误和最近重启原因 |

连接成功先调用 `check` 和 `status`，不擅自启动第二个采集进程。所有按钮随实际状态变化，调用失败还原按钮状态。编码参数同时显示“输入值”与“运行值”，避免将提交成功误判为实际采集成功。

## 4. 已实现控制协议

SSH 上执行固定入口，命令名只从允许列表选择。配置 JSON 写入 channel stdin，不把用户输入拼接到 shell 命令。请求超时采用 35 秒；轮询 `status` 默认每秒一次，上一轮未结束则不叠加请求。

开发板 Bash，查询状态：

```bash
python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py status
```

`python3` 启动板端 Python；绝对路径指向统一控制入口；`status` 返回 JSON，查询不会重新打开摄像头。上位机通过 SSH 执行同一条命令并解析 stdout。

开发板 Bash，启动并从标准输入读取设置：

```bash
printf '%s\n' '{"device":"/dev/video44","codec":"h265","width":1920,"height":1080,"fps":30,"bitrate":2500000,"gop":30}' | python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py start --config-stdin
```

`printf` 输出一行 JSON；管道把 JSON 送入控制程序；`start` 启动直播，`--config-stdin` 从 stdin 读取设置。`bitrate` 单位 bit/s；`gop` 为关键帧间隔帧数。界面直接向 SSH stdin 写相同 JSON，不需运行 `printf`。

| 命令 | 含义 | 上位机行为 |
| --- | --- | --- |
| check | 编码器、采集节点、运行环境能力 | 连接时检查；缺少硬编直接显示失败 |
| start / stop | 开始/结束直播 | stop 先封口正在进行的录像，再结束采集 |
| status | 实际进程、帧进度、VPU、RTSP、录像 | 周期查询；以实际 frame 前进判断运行 |
| preview-start / preview-stop | 板端 HDMI 播放 | 不开启第二个摄像头采集 |
| record-start / record-stop | 新 MP4 / 正常结束并验证 | 完成前不提供“录像成功”状态 |
| snapshot | 当前流生成 JPEG | 显示返回路径，可 SFTP 下载 |
| logs | 最近运行日志 | 按需查询，不持续大批量拉取 |

结果结构为 `{"ok":true,"result":...}` 或 `{"ok":false,"error":...}`。字段以 [avctl.py](../board/ffmpeg_pipeline/avctl.py) 为准，GUI 不根据英文日志猜测成功。直播格式变更后 RTSP 地址不变；客户端销毁旧解码器并重新读取新流。

SSH 断开只代表控制连接断开，板端服务仍可能正常运行。重连后先查询状态再操作。开始录像操作禁用重复点击，避免超时重试创建多个文件。未来可扩展请求 ID 与幂等键。

## 5. 文件与凭据

密码交给 Windows Credential Manager，例如使用 keyring 访问；配置文件只存 IP、端口、用户、密钥位置和编码参数。主机指纹变化必须显式提示，不静默接受。不要把密码、私钥、实际运行快照写进 Git。

SFTP 下载只允许板端 `recordings/` 与 `snapshots/` 内由接口返回的文件；先校验规范化路径，再写本地 `.part`，核对长度后改名。首版下载限制一个任务；录像仍在写入时不下载成“完整 MP4”。删除文件应是后续独立功能，当前不会自动清理板端文件。

## 6. 参数与相机能力边界

首版支持 H.264/H.265 选择，板端入口已有两种 rkmpp 编码器检测与选择；本轮完整硬件验收使用 H.265，H.264 切换仍需下一阶段独立实测。分辨率和帧率输入须同时满足板端范围与设备实际支持，不能只验证控件数值。

曝光、增益、白平衡、ROI、动态码率和算法按钮先按能力报告展示。RKAIQ 自动曝光仍在工作，不直接写传感器寄存器或在 GUI 中绕过 3A。下一阶段先研究厂商 RKAIQ 手动控制接口，再增加安全切换自动/手动的板端 API。

JPEG 截图、MP4 录像和统计为本轮已实现处理；目标检测、外网访问、多路相机与音频同步尚未开发。浏览器预览需要另外选择 WebRTC/HLS 与浏览器兼容编码，不能假定 HTML 能直接播放 RTSP H.265。

## 7. 下一阶段开发与验收

1. 先实现连接页和 SSH Worker，验证主机指纹、超时、断线重连、JSON 错误及状态同步。
2. 实现单画面视频页与 FFmpeg Worker，验证连续解码、最新帧队列和退出清理。
3. 接入启停与编码页，测试两种编码、参数受控重启、录像期间拒绝切换。
4. 接入录像、截图、SFTP 下载和日志页，验证下载文件可回放、失败可重试。
5. 在 Windows 上运行 30 分钟，覆盖 SSH/网络故障与十次连接关闭；检查无残留解码进程、无 UI 卡顿。

首版交付后再接入算法 Worker：独立订阅解码帧，限制队列和耗时，避免算法延迟阻塞视频与控制。PyAV 可以在该阶段做帧和时间戳接口；采用前需用本机 Windows 依赖版本测试。
