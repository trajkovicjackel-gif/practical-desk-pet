# -*- coding: utf-8 -*-
"""Full-field transparent overlay: basketball aiming line + motion trail.

The window covers the whole play field, is click-through (mouse-transparent),
and repaints whenever the controller tells it to. No custom hoop is drawn —
the real desktop Recycle Bin icon is the target.
"""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QPolygonF
from PySide6.QtWidgets import QWidget


class OverlayWindow(QWidget):
    def __init__(self, field_rect):
        super().__init__()
        self.field = field_rect  # (x, y, w, h) in virtual desktop coords
        self.trail = []          # list of (x, y), oldest first
        self.aim = []            # aiming polyline points (dashed, no fade)
        self.effects = []        # explosion effects: {cx,cy,t,max_r,life}
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(QRectF(*self.field).toRect())

    def set_trail(self, points):
        """points: list of (x, y) behind the ball, oldest first."""
        self.trail = points
        self.update()

    def set_aim(self, points):
        """Aiming line while dragging the slingshot (full dashed line)."""
        self.aim = points
        self.update()

    def set_effects(self, effects):
        """Explosion effects: expanding rings that fade out."""
        self.effects = effects
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # explosion effects: expanding rings with fading alpha + sparkle
        for ef in self.effects:
            prog = ef["t"] / max(0.01, ef["life"])
            radius = 8 + ef["max_r"] * min(1.0, prog)
            alpha = int(230 * (1.0 - prog))
            p.setPen(QPen(QColor(255, 170, 60, max(0, alpha)), 5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(ef["cx"], ef["cy"]), radius, radius)
            p.setPen(QPen(QColor(255, 120, 40, max(0, int(alpha * 0.7))), 3))
            p.drawEllipse(QPointF(ef["cx"], ef["cy"]), radius * 0.65, radius * 0.65)
            p.setPen(QPen(QColor(255, 230, 150, max(0, int(alpha * 0.8))), 2))
            p.drawEllipse(QPointF(ef["cx"], ef["cy"]), radius * 0.32, radius * 0.32)

        # aiming line: complete dashed polyline, no fade
        if self.aim:
            p.setPen(QPen(QColor(255, 220, 90, 200), 3, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            poly = QPolygonF([QPointF(x, y) for x, y in self.aim])
            p.drawPolyline(poly)
            # small launch-direction marker at the head
            if len(self.aim) > 2:
                hx, hy = self.aim[0]
                p.setPen(QPen(QColor(255, 255, 255, 220), 2))
                p.drawEllipse(QPointF(hx, hy), 5, 5)

        # motion trail: newer dots brighter, older dots fade out
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail):
            t = (i + 1) / max(1, n)          # 0 (oldest) .. 1 (newest)
            alpha = int(24 + 200 * t)
            radius = 3.5 + 2.0 * t
            grad = QRadialGradient(tx, ty, radius + 2)
            grad.setColorAt(0, QColor(255, 220, 90, min(alpha, 230)))
            grad.setColorAt(1, QColor(255, 220, 90, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(tx, ty), radius, radius)
        p.end()
