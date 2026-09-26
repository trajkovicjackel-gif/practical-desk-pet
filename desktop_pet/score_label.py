# -*- coding: utf-8 -*-
"""Small always-on-top score label shown while a game mode is active."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QWidget


class ScoreLabel(QWidget):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(0, 0, 210, 42)

    def set_score(self, text):
        self.text = text
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(30, 30, 30, 190), 2))
        p.setBrush(QColor(20, 20, 20, 150))
        p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 10, 10)
        p.setPen(QColor(255, 255, 255, 235))
        f = QFont("Microsoft YaHei", 12, QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, self.text)
        p.end()
