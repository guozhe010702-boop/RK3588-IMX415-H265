"""Native Windows layout probe. Run in a separate process per QT_SCALE_FACTOR."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from evm_console.window import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["EVM_CONSOLE_DATA"] = str((args.output / "user-data").resolve())
    app = QApplication([])
    window = MainWindow()
    window.show()
    results = []

    def probe():
        try:
            for width, height in [(1420, 900), (1024, 700), (760, 480)]:
                available = app.primaryScreen().availableGeometry()
                window.resize(min(width, available.width()-24), min(height, available.height()-40))
                for index in range(5):
                    window.select_page(index)
                    app.processEvents()
                    for _ in range(3):
                        app.processEvents()
                        time.sleep(0.02)
                    clipped = [label.text()[:70] for label in window.findChildren(QLabel)
                        if label.isVisible() and not label.wordWrap()
                        and label.size().width()+2 < label.sizeHint().width()]
                    buttons = [b.text() for b in window.findChildren(QPushButton)
                        if b.isVisible() and b.size().width()+2 < b.minimumSizeHint().width()]
                    scroll = window.pages.currentWidget()
                    entry = {"requested": [width, height], "actual": [window.size().width(), window.size().height()],
                        "page": index, "clippedLabels": clipped, "clippedButtons": buttons,
                        "pageHorizontalOverflow": scroll.horizontalScrollBar().maximum(),
                        "rootScroll": [window.root_scroll.horizontalScrollBar().maximum(),
                                       window.root_scroll.verticalScrollBar().maximum()]}
                    results.append(entry)
                    window.grab().save(str(args.output / f"{width}x{height}-page{index}.png"))
                    if index == 4:
                        window.trend_toggle.setChecked(True)
                        window.details_toggle.setChecked(True)
                        app.processEvents()
                        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum()//2)
                        app.processEvents()
                        window.grab().save(str(args.output / f"{width}x{height}-page{index}-trends.png"))
                    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                    window.root_scroll.verticalScrollBar().setValue(window.root_scroll.verticalScrollBar().maximum())
                    app.processEvents()
                    window.grab().save(str(args.output / f"{width}x{height}-page{index}-bottom.png"))
                    if index == 4:
                        window.trend_toggle.setChecked(False)
                        window.details_toggle.setChecked(False)
                    scroll.verticalScrollBar().setValue(0)
                    window.root_scroll.verticalScrollBar().setValue(0)
            report = {"scale": os.getenv("QT_SCALE_FACTOR", "system"),
                      "dpr": window.devicePixelRatioF(), "checks": results,
                      "passed": all(not r["clippedLabels"] and not r["clippedButtons"]
                                    and r["pageHorizontalOverflow"] == 0 for r in results)}
            (args.output / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report), flush=True)
        finally:
            window.close()
    QTimer.singleShot(200, probe)
    app.exec()


if __name__ == "__main__":
    main()
