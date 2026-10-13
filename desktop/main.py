import argparse
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from pathlib import Path
from evm_console import __version__
from evm_console.window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="EVM3588 Camera Console")
    parser.add_argument("--version", action="store_true")
    parser.add_argument(
        "--connect", action="store_true", help="Connect using the saved connection profile"
    )
    args = parser.parse_args()
    if args.version:
        print(__version__)
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("EVM3588CameraConsole")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(
        QIcon(
            str(
                Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
                / "assets/camera.svg"
            )
        )
    )
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    area = app.primaryScreen().availableGeometry()
    window.resize(min(1420, area.width() - 30), min(900, area.height() - 30))
    window.show()
    if args.connect:
        QTimer.singleShot(300, window.connect_board)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
