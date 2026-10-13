# Third-party components

The portable application includes dynamically loaded Qt/PySide6 and Python packages. Installed license files are copied into `licenses/`; the exact versions and FFmpeg build configuration are recorded in `build-manifest.json`.

| Component | Upstream / license information |
| --- | --- |
| PySide6 / Qt | https://www.qt.io/qt-for-python / https://doc.qt.io/qtforpython-6/licenses.html ; LGPLv3/GPLv3/commercial options; consult included component licenses |
| Paramiko | https://github.com/paramiko/paramiko ; LGPL-2.1 |
| keyring | https://github.com/jaraco/keyring ; MIT |
| Python | https://www.python.org/ ; PSF license |
| PyInstaller | https://github.com/pyinstaller/pyinstaller ; GPL with bootloader distribution exception |
| FFmpeg | https://ffmpeg.org/legal.html ; this package uses the existing Gyan full build, configured with `--enable-gpl --enable-version3` |
| Windows FFmpeg build | https://www.gyan.dev/ffmpeg/builds/ ; upstream source https://github.com/FFmpeg/FFmpeg ; packaging source https://github.com/GyanD/codexffmpeg |

BelEye and camera-control-desktop were architecture references. Their code is not copied into this application. The project does not assign a new overall open-source license. Review individual dependency licenses when redistributing binaries.
