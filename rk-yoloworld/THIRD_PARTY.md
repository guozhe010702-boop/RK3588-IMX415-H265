# 第三方组件与来源

本工程新增的队列、采集、RKNN 适配、绘制、NUT 输出和运行工具见源码目录。后处理的三尺度 distance-box 解码公式参考 Rockchip YOLO-World 示例及下列固定参考版本，保留对应许可。

| 组件 | 固定来源 / 版本 | 使用范围 |
|---|---|---|
| 参考实时工程与 CLIP tokenizer | `zyp0424/-RK3588-yolo-world-`，`5b6995905425115029ad63820a007368d2a2882f` | 分词器与参考代码；MIT，部分参考文件另带 Apache-2.0 声明 |
| RKNN API 头文件 / 私有 runtime | RKNN-Toolkit2 v2.3.2；包内 runtime `2.3.2 (429f97ae6b@2025-04-09)` | NPU 推理；Rockchip 版权声明见 licenses |
| RGA | `https://gitee.com/nyanmisaka/rga.git`，`1d330cc28551943bed3380261a5a9c6fbd58ff53` | 使用本板已验证的私有库与匹配头文件：Meson 发行库名 2.1.0、im2d API 1.10.4；Apache-2.0 |
| 私有 NUT muxer | FFmpeg 7.1.1 官方源码 | 仅 libavformat/libavcodec/libavutil，动态链接；LGPL-2.1-or-later |
| 实际硬编 FFmpeg | 板端现有 ffmpeg-rockchip，`d90e3a1c18d7929383cf88c1b3da2e2d1c966cbf` | 独立进程、独立库环境；不替换系统 FFmpeg |
| 模型、类别文件和示例图片 | 用户提供的部署目录 | 仅本地导入/交付；不进入 Git，不代替模型原作者的许可 |

`sources.lock.json` 记录下载 URL、源码/头文件 SHA-256。部署目录内 `package-manifest.json` 记录模型和 runtime 校验值；`build-manifest.json` 记录编译器与运行库校验值。包内原始 RGA 保留在本地 `dist/package-libraries/` 供核验，没有覆盖本工程已通过实测的 RGA。

本地源码 ZIP 包含 tokenizer、SDK 头文件、FFmpeg 与 RGA 源码归档及构建脚本；部署 ZIP 同时携带该源码 ZIP。可以替换私有 FFmpeg 共享库后重新链接和运行，不使用静态链接规避 LGPL 的替换条件。RKNN runtime 为厂商组件，使用和再分发需遵守附带的 Rockchip 版权声明。

原视频工程的 RAW 调度辅助类仅由**本板测试/恢复工具**调用，继承之前已启用的三个 AIQ RAW 传输线程调度，并在测试结束恢复。C++ 检测程序及普通启动脚本不依赖原 Python 控制模块。
