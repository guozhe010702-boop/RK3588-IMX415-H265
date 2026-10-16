# 开发工具

所有脚本均从自己的文件位置计算项目根目录，不依赖当前终端目录。

| 子目录 | 入口 | 用途 |
| --- | --- | --- |
| `deploy/` | `deploy.ps1` | 上传当前板端源码；`-ListOnly` 离线列出计划 |
| `deploy/` | `refresh_status.ps1` | 只读采样到 `web/board_status.js` |
| `docs/` | `check_guide.py` | 检查 Markdown 相对链接与命令语法，以及唯一网页的链接 |
| `release/` | `package_project.py` | 只生成 `releases/av_dev-source.zip`，不创建第二份源码 |
| `dev/` | `make_ffmpeg_patch.py` | 根据锁定上游生成 NV12M 补丁；下载缓存放在 `.cache/` |
| `tests/` | `test_rtsp_client.py` | 用电脑 FFmpeg 验证 RTSP 可解码性 |

源码启动和打包仍在 `desktop/run.ps1`、`desktop/build.py`。这些与桌面源码一同维护；EXE 打包输出放到 `releases/desktop/`，中间缓存放到 `.cache/desktop-build/`。
