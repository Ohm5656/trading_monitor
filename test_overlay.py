import sys

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QPen, QColor, QFont


class Overlay(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def paintEvent(self, event):
        painter = QPainter(self)

        # จุด BOS
        painter.setPen(QPen(QColor(0, 255, 0), 3))
        painter.drawLine(700, 400, 900, 400)

        painter.setFont(
            QFont("Arial", 18, QFont.Weight.Bold)
        )

        painter.drawText(700, 390, "BOS #1")

        # จุด CHoCH
        painter.setPen(QPen(QColor(255, 100, 100), 3))
        painter.drawLine(400, 600, 600, 600)

        painter.drawText(400, 590, "CHoCH")


app = QApplication(sys.argv)

overlay = Overlay()
overlay.show()

sys.exit(app.exec())