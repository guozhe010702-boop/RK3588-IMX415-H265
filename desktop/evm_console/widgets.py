from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QPen, QColor
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFrame

STYLE = """
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; color: #dce7f4; }
QMainWindow,QDialog { background: #0b1220; }
QWidget#page { background: #121e30; }
QWidget#header { background: #101c2e; border-bottom: 1px solid #263650; }
QFrame#panel,QFrame#metric { background: #121e30; border: 1px solid #263650; border-radius: 12px; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#subtitle,QLabel#muted { color: #8a9bb2; }
QLabel#section { font-size: 17px; font-weight: 600; }
QLabel#metricValue { font-size: 23px; font-weight: 700; color: #71dfec; }
QPushButton { background: #1b2d44; border: 1px solid #344a66; border-radius: 7px; padding: 9px 13px; }
QPushButton:hover { background: #29415e; border-color: #587da6; }
QPushButton:pressed { background: #142237; }
QPushButton:disabled { color: #586a82; background: #142033; border-color: #203047; }
QPushButton#primary { background: #087f91; border-color: #22b7c9; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #0c9caf; }
QPushButton#primary:disabled { color: #586a82; background: #142033; border-color: #203047; }
QPushButton#danger { background: #51232c; border-color: #9b4856; }
QPushButton#danger:disabled { background: #142033; border-color: #203047; }
QPushButton#tab:checked { background: #123d53; border-color: #26b1c4; color: #83ecf3; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox { background: #0c1728; border: 1px solid #354b68; border-radius: 6px; padding: 7px; min-height: 21px; }
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus { border-color: #27bfd1; }
QComboBox QAbstractItemView { background: #152438; selection-background-color: #236079; }
QPlainTextEdit,QTableWidget { background: #0b1728; border: 1px solid #293e58; border-radius: 7px; selection-background-color: #20516a; }
QHeaderView::section { background: #1b2c42; border: 0; border-bottom: 1px solid #344a66; padding: 8px; }
QCheckBox { spacing: 7px; } QCheckBox::indicator { width: 16px; height: 16px; }
QProgressBar { background: #0c1728; border: 1px solid #354b68; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #138e9f; border-radius: 4px; }
QScrollArea { border: 0; background: transparent; } QScrollBar:vertical { background: #101c2e; width: 9px; }
QScrollBar::handle:vertical { background: #3a516d; border-radius: 4px; min-height: 25px; }
QToolTip { background: #20344e; border: 1px solid #5a789b; color: white; }
"""


class Badge(QLabel):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.set_state(False)

    def set_state(self, ok, text=None):
        self.setText("●  " + self.title + " · " + (text or ("正常" if ok else "未连接")))
        color = "#6de0b7" if ok else "#8d9db3"
        self.setStyleSheet(
            f"color:{color};background:#15263a;border:1px solid #2b405b;border-radius:14px;padding:6px 10px;"
        )


class Metric(QFrame):
    def __init__(self, title, value="—"):
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        layout.addWidget(label)
        layout.addWidget(self.value)


class VideoCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.image = None
        self.submitted_frames = 0
        self.painted_frames = 0
        self.painted_sequence = 0
        self.discarded_frames = 0
        self.message = "连接开发板，打开实时画面"
        self.setMinimumSize(400, 180)

    def set_frame(self, data, width, height):
        if self.submitted_frames != self.painted_sequence:
            self.discarded_frames += 1
        self.submitted_frames += 1
        self.image = QImage(data, width, height, width * 3, QImage.Format.Format_BGR888).copy()
        self.message = ""
        self.update()

    def set_message(self, text, clear=False):
        self.message = text
        if clear:
            self.image = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#070e19"))
        if self.image is not None:
            size = self.image.size()
            size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(
                (self.width() - size.width()) / 2,
                (self.height() - size.height()) / 2,
                size.width(),
                size.height(),
            )
            painter.drawImage(target, self.image)
            if self.painted_sequence != self.submitted_frames:
                self.painted_sequence = self.submitted_frames
                self.painted_frames += 1
            if self.message:
                painter.fillRect(
                    QRectF(0, self.height() - 42, self.width(), 42), QColor(5, 12, 24, 220)
                )
                painter.setPen(QColor("#dce7f4"))
                painter.drawText(
                    QRectF(12, self.height() - 40, self.width() - 24, 38),
                    Qt.AlignmentFlag.AlignVCenter,
                    self.message,
                )
        else:
            painter.setPen(QPen(QColor("#102235"), 1))
            for x in range(0, self.width(), 36):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), 36):
                painter.drawLine(0, y, self.width(), y)
            painter.setPen(QPen(QColor("#2d7891"), 3))
            cx = self.width() / 2
            cy = self.height() / 2 - 45
            painter.drawRoundedRect(QRectF(cx - 42, cy - 28, 84, 56), 8, 8)
            painter.drawEllipse(QRectF(cx - 15, cy - 15, 30, 30))
            painter.setPen(QColor("#a6c1d7"))
            painter.drawText(
                QRectF(20, cy + 55, self.width() - 40, 60),
                Qt.AlignmentFlag.AlignHCenter,
                self.message,
            )
        painter.end()
