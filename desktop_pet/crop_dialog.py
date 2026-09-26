# -*- coding: utf-8 -*-
"""Skin crop dialog: pick any CIRCULAR part of the uploaded image.

Drag defines a circle (center = press point, radius = drag distance). The
pet displays skins inside a circle, so the crop region is bounded by the
circle; the saved file is the circle's bounding square (the pet clips it).
The result is saved under %APPDATA%/DesktopPet/skins/ and its path returned.
"""

import os

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

VIEW_MAX = 720  # max displayed size (either axis)


class CropDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择皮肤显示区域（圆形选取）")
        self.src = QPixmap(image_path)
        if self.src.isNull():
            raise ValueError("无法读取图像")

        # scale for display
        scale = min(1.0, VIEW_MAX / max(self.src.width(), self.src.height()))
        self.view_w = max(1, int(self.src.width() * scale))
        self.view_h = max(1, int(self.src.height() * scale))
        self.scale = scale
        self.preview = QPixmap(self.src).scaled(
            self.view_w, self.view_h,
            Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self.sel = None        # (cx, cy, radius) in DISPLAY coordinates
        self._drag_start = None
        self._drag_mode = None   # "new" (draw circle) | "move" (drag selection)
        self.cropped_path = None

        self.canvas = _Canvas(self)
        self.canvas.setFixedSize(self.view_w, self.view_h)

        tip = QLabel("操作提示：按住左键拖出圆形选区（半径=拖动距离）；"
                     "拖动选区中心的「十字」可整体移动选区；"
                     "在选区内点击鼠标右键可重置并重新框选；"
                     "不选择则默认裁取图像中心最大内切圆。")
        tip.setWordWrap(True)

        ok = QPushButton("确定")
        cancel = QPushButton("取消")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(tip)
        layout.addWidget(self.canvas, alignment=Qt.AlignCenter)
        layout.addLayout(row)

    # -------------------------------------------------------------- crop
    def _accept(self):
        if self.sel is None:
            # centered largest inscribed circle of the source
            size = min(self.src.width(), self.src.height())
            sx = (self.src.width() - size) // 2
            sy = (self.src.height() - size) // 2
            box = (sx, sy, size, size)
        else:
            cx, cy, radius = self.sel
            sx = int(cx / self.scale)
            sy = int(cy / self.scale)
            size = int(radius * 2 / self.scale)
            size = max(4, min(size, self.src.width(), self.src.height()))
            sx = max(0, min(sx - size // 2, self.src.width() - size))
            sy = max(0, min(sy - size // 2, self.src.height() - size))
            box = (sx, sy, size, size)

        out_dir = os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"),
            "DesktopPet", "skins")
        os.makedirs(out_dir, exist_ok=True)
        import time
        out = os.path.join(out_dir, f"skin_{int(time.time() * 1000)}.png")

        cropped = self.src.copy(*box)
        if not cropped.save(out, "PNG"):
            self.reject()
            return
        self.cropped_path = out
        self.accept()

    def start_drag(self, pos):
        self._drag_start = pos
        # pressing near the selection center moves the whole selection
        if self.sel is not None:
            cx, cy, radius = self.sel
            if abs(pos.x() - cx) <= 12 and abs(pos.y() - cy) <= 12:
                self._drag_mode = "move"
                return
        self._drag_mode = "new"
        if self.sel is not None:
            self.sel = None          # start a fresh circle
            self.canvas.update()

    def update_drag(self, pos):
        if self._drag_start is None:
            return
        if self._drag_mode == "move" and self.sel is not None:
            cx, cy, radius = self.sel
            dx = pos.x() - self._drag_start.x()
            dy = pos.y() - self._drag_start.y()
            ncx = int(max(radius, min(cx + dx, self.view_w - radius)))
            ncy = int(max(radius, min(cy + dy, self.view_h - radius)))
            self.sel = (ncx, ncy, radius)
            self._drag_start = pos
            self.canvas.update()
            return
        x0, y0 = self._drag_start.x(), self._drag_start.y()
        x1, y1 = pos.x(), pos.y()
        radius = int(max(8, abs(x1 - x0), abs(y1 - y0)))
        cx = int(max(0, min(x0, self.view_w - 1)))
        cy = int(max(0, min(y0, self.view_h - 1)))
        radius = min(radius, cx, cy, self.view_w - cx, self.view_h - cy)
        radius = max(8, radius)
        self.sel = (cx, cy, radius)
        self.canvas.update()

    def end_drag(self):
        self._drag_start = None
        self._drag_mode = None

    def right_click(self, pos):
        """Right-click inside the selection resets it for re-selection."""
        if self.sel is not None:
            cx, cy, radius = self.sel
            d = ((pos.x() - cx) ** 2 + (pos.y() - cy) ** 2) ** 0.5
            if d <= radius:
                self.sel = None
                self._drag_start = None
                self._drag_mode = None
                self.canvas.update()


class _Canvas(QLabel):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setPixmap(dialog.preview)
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dialog.start_drag(e.position())
        elif e.button() == Qt.RightButton:
            self.dialog.right_click(e.position())
        e.accept()

    def mouseMoveEvent(self, e):
        self.dialog.update_drag(e.position())
        e.accept()

    def mouseReleaseEvent(self, e):
        self.dialog.end_drag()
        e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.dialog.sel is None:
            return
        cx, cy, radius = self.dialog.sel
        p = QPainter(self)
        # dim everything OUTSIDE the circle
        p.setBrush(QColor(0, 0, 0, 90))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.width(), self.height()))
        path.addEllipse(QPointF(cx, cy), radius, radius)
        path.setFillRule(Qt.OddEvenFill)
        p.drawPath(path)
        # circle border + center mark
        p.setPen(QPen(QColor(255, 140, 40), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        p.setPen(QPen(QColor(255, 255, 255, 200), 1))
        p.drawLine(QPointF(cx - 8, cy), QPointF(cx + 8, cy))
        p.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))
        p.end()
