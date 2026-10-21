# av_dev — RK3588 / IMX415 相机项目

主程序是 **Windows 桌面控制台 + RK3588 FFmpeg/VPU 控制服务**。IMX415/con7 经 `/dev/video44` 采集，硬编后通过 RTSP 提供电脑预览、HDMI、录像和截图。

8K 扩展已改用 **IMX415 实拍**：[新增程序清单、实测与完整操作](docs/guides/8K_HEVC方案与实测.md)。板端实时完成 4K 实拍→RGA 放大→8K30 VPU 硬编/MP4/RTSP；8K60 硬解使用真实 4K60 录像经电脑离线空间放大后的文件，无合成图、无补帧。IMX415 原生仍为 4K，不能把放大称为原生 8K；本轮是短测，尚未完成 8K 长测或桌面 8K 按钮。

本轮直接运行的新增入口是 `tools/tests/run_imx415_8k.py`（电脑）与 `board/ffmpeg_pipeline/tests/imx415_8k.py`（板端）；8K60 素材准备在 `tools/tests/prepare_camera_8k60.py`。上一轮合成基准保留历史标识，不作为实拍验收。

当前开发版本 **1.2.2**：实时带宽/CPU/内存卡片、自适应分栏、60 fps 预览、十分钟趋势、CSV 和板端硬解显示。真实 4K60 的能力、采集缺口和电脑长测分别记录，不以配置值冒充实际帧率。详细范围见 [验收记录](docs/history/4K60与性能监测验收.md)，使用与指标口径见 [性能指南](docs/guides/4K60与性能监测.md)。普通默认仍为 1080p30。

## 目录与入口

```text
av_dev/
├─ README.md                  从这里开始
├─ board/                     当前板端程序
│  ├─ ffmpeg_pipeline/         avctl.py、控制模块、配置、构建和测试
│  ├─ bsp/                     独立实验驱动候选，不随普通程序部署
│  └─ diagnostics/            环境与编码器检查
├─ desktop/                   Windows 主程序：main.py、evm_console/、tests/
├─ rk-yoloworld/              独立 YOLO-World 实时检测：src/、include/、tools/、tests/
├─ examples/                  学习代码，与主程序分开
│  ├─ mpp_c_api/              V4L2 → MPP C API
│  └─ gstreamer/              原 GStreamer 示例
├─ tools/                     按用途分类的开发工具
│  ├─ deploy/                 部署、网页状态采样
│  ├─ docs/                   Markdown 链接与命令检查
│  ├─ release/                源码 ZIP 打包
│  ├─ dev/                    FFmpeg 补丁生成
│  └─ tests/                  RTSP 客户端验证
├─ docs/                      Markdown 文档，不再生成多套网页
│  ├─ architecture/           程序逻辑与设计参考
│  ├─ guides/                 操作指南
│  ├─ history/                历史验收与版本记录
│  └─ assets/                 架构图
├─ web/                       唯一网页 index.html 与状态脚本
├─ releases/                  EXE ZIP、源码 ZIP（本地交付物）
└─ reference/                 SDK 与厂商资料（本地参考）
```

`.venv-desktop/` 是现有独立 Python 环境；`.cache/` 用于可重新生成的构建缓存。二者不作为源码提交。

| 目的 | 位置 |
| --- | --- |
| 阅读核心逻辑和模块职责 | [项目程序逻辑](docs/architecture/项目程序逻辑与目录导航.md) |
| 修改 Windows 程序 | [desktop](desktop/README.md)，入口 `desktop/main.py` |
| 修改板端程序 | [FFmpeg 控制服务](board/ffmpeg_pipeline/README.md)，入口 `avctl.py` |
| 实时目标检测、双端画面与 CPU/NPU 监测 | [YOLO-World 完整操作与源码说明](rk-yoloworld/README.md)，正式源码仅维护在这个子目录 |
| 使用桌面软件 | [桌面操作指南](docs/guides/Windows_相机控制台操作指南.md) |
| 部署与命令行操作 | [FFmpeg 指南](docs/guides/FFmpeg_全链路操作指南.md) |
| 学习 MPP / GStreamer | [examples](examples/README.md) |
| 查看方案和采样状态 | [唯一网页](web/index.html) |
| 找其它说明或历史实测 | [文档目录](docs/README.md) |

## 开发时使用

以下命令都在 **电脑 PowerShell，av_dev 根目录**执行。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\desktop\run.ps1
```

解释：启动源码桌面程序；`-NoProfile` 不加载个人配置，`-ExecutionPolicy Bypass` 仅对本次进程放行，`-File` 指定脚本。使用现有 `.venv-desktop`，首次安装见操作指南。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\deploy\deploy.ps1 -ListOnly
```

解释：`-ListOnly` 只列出将上传的本地和板端路径，不连接或修改开发板。去掉该参数才真正上传；默认上传主程序和诊断脚本，学习示例需显式加 `-IncludeExamples`，编译 MPP 示例用 `-BuildExamples`。

```powershell
.\.venv-desktop\Scripts\python.exe -B -m pytest .\desktop\tests -q -p no:cacheprovider
```

解释：运行桌面回归；`-B` 不生成字节码缓存，`-q` 简洁输出，最后一组参数关闭 pytest 缓存。测试不启停真实开发板。

```powershell
python .\tools\release\package_project.py
```

解释：只生成 `releases/av_dev-source.zip`，不再复制一份可编辑的“音视频代码包”目录；源码仍只维护根目录这一份。

## 本次清理的边界

此前已清除重复解压目录、旧重复包、临时验证目录和构建缓存，移除重复 README.txt、文档 HTML 及 HTML 生成器。性能功能在原目录上增量开发，实际部署与验收范围见 [性能验收记录](docs/history/4K60与性能监测验收.md)。

整理前完整 Git 历史、源码及历史验证材料已归档到相邻目录 `../av_dev_archive_20261016/`。归档不在项目内部，避免再次混入日常开发目录；操作明细在归档的 `migration.json`。源码改动见 Git 历史。

开发板运行路径保持 `/userdata/av_dev/ffmpeg_pipeline/`，个人配置和录像位置不变。真实凭据、录像、SDK、状态快照和生成包不进入 GitHub。
