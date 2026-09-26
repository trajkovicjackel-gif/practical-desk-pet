# -*- coding: utf-8 -*-
"""Pong platform windows (top = AI paddle, bottom = user paddle)."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QWidget

PLATFORM_W = 130
PLATFORM_H = 14


class PlatformWindow(QWidget):
    def __init__(self, x, y, role):
        super().__init__()
        self.role = role  # "top" (AI) | "bottom" (user)
        self.w = PLATFORM_W
        self.h = PLATFORM_H
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(int(x), int(y), self.w, self.h)
        self.show()

    def set_platform(self, x, y):
        self.move(int(x), int(y))

    def get_rect(self):
        return (self.x(), self.y(), self.w, self.h)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.h)
        if self.role == "top":
            grad.setColorAt(0.0, QColor("#4FC3F7"))
            grad.setColorAt(1.0, QColor("#0277BD"))
        else:
            grad.setColorAt(0.0, QColor("#81C784"))
            grad.setColorAt(1.0, QColor("#2E7D32"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor(20, 20, 20, 160), 2))
        p.drawRoundedRect(QRectF(1, 1, self.w - 2, self.h - 2), 6, 6)
        # little direction hint on the user paddle
        if self.role == "bottom":
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawText(QRectF(0, 0, self.w, self.h), Qt.AlignCenter, "◄ ►")
        p.end()
