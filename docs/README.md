# 文档导航

先读 [项目程序逻辑与目录导航](architecture/项目程序逻辑与目录导航.md)。它说明当前入口、模块职责、运行流程、状态与线程，以及修改功能应该定位哪个文件。

| 目的 | 文档 |
| --- | --- |
| 整体理解程序与目录 | [项目程序逻辑与目录导航](architecture/项目程序逻辑与目录导航.md) |
| 查看这次结构整理与验证 | [项目结构整理记录](history/项目结构整理记录.md) |
| 直接使用桌面软件 | [Windows 相机控制台操作指南](guides/Windows_相机控制台操作指南.md) |
| 看帧率、流量、趋势与 CSV | [4K60 与性能监测](guides/4K60与性能监测.md) |
| 看真实 4K30、合成 4K60 与 BSP 的验证边界 | [1.2.0 验收记录](history/4K60与性能监测验收.md) |
| 部署、构建与命令行操作 | [FFmpeg 全链路操作指南](guides/FFmpeg_全链路操作指南.md) |
| 学习 V4L2 / MPP C API | [路线二操作与修改指南](guides/路线二_MPP_C_API_操作与修改指南.md) |
| 理解 1.1.0 的优化与以后候选工作 | [控制台优化调研与实施](architecture/Windows_控制台优化调研与实施.md) |
| 回看最初设计 | [Windows 上位机设计与开源调研](architecture/Windows_上位机设计与开源调研.md) |
| FFmpeg 的历史实测证据 | [FFmpeg 全链路验收记录](history/FFmpeg_全链路验收记录.md) |
| 桌面 1.0.0 的历史实测证据 | [Windows 相机控制台验收记录](history/Windows_相机控制台验收记录.md) |
| 桌面 1.1.0 的实测证据 | [控制台优化验收记录](history/Windows_控制台优化验收记录.md) |

文档只维护 Markdown，在 IDE 或 GitHub 阅读。`architecture/` 解释程序，`guides/` 给出操作步骤，`history/` 保存旧版本实测。只保留 `web/index.html` 一个方案与状态网页。

验收记录注明对应版本与范围。历史 30 分钟测试属于当时版本，本轮结构回归与历史硬件验收分别记录。方案网页是总入口与手动状态快照，程序逻辑文档是源码阅读入口。
