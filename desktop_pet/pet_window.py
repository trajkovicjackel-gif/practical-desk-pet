# -*- coding: utf-8 -*-
"""The circular, translucent, always-on-top pet window.

One window per "object": the pet itself (idle / balloon), or each ball in
pong / basketball mode. Rendering (skin / default face / balloon + water)
and input (drag, slingshot, click-to-slap, context menu) live here.
"""

import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QColor, QBrush, QPen, QPainterPath, QLinearGradient
from PySide6.QtWidgets import QWidget, QMenu

ROLE_PET = "pet"
ROLE_PONG = "pong_ball"
ROLE_BASKET = "basket_ball"
ROLE_BALLOON = "balloon"


class PetWindow(QWidget):
    def __init__(self, controller, role=ROLE_PET, radius=80):
        super().__init__()
        self.controller = controller
        self.role = role
        self.radius = radius
        self.skin = None          # QPixmap or None
        self.water_pct = 0.0      # balloon only
        self.rotation_angle = 0.0 # record-state rotation (degrees)
        self.tonearm_target = False   # where the tonearm should end up
        self.tonearm_progress = 0.0   # animated 0..1 (smooth transition)
        self._drag_start = None   # (global_pos, t_ms)
        self._dragging = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.resize(radius * 2, radius * 2)
        self._ctx_menu = None

    # ------------------------------------------------------------------ api
    def apply_appearance(self, radius, skin_path=None):
        self.radius = radius
        if skin_path:
            pix = QPixmap(skin_path)
            if not pix.isNull():
                self.skin = pix
        else:
            self.skin = None   # 皮肤路径为空 → 恢复默认外观（修复无法清除皮肤）
        self.resize(int(radius * 2), int(radius * 2))
        self.update()

    def set_water(self, pct):
        self.water_pct = max(0.0, min(100.0, pct))
        self.update()

    def set_rotation(self, angle_deg):
        self.rotation_angle = angle_deg % 360.0
        self.update()

    def set_tonearm_engaged(self, engaged):
        """Set the tonearm TARGET; the actual position animates smoothly."""
        self.tonearm_target = bool(engaged)
        self.update()

    def animate_tonearm(self, dt):
        """Smoothly move the tonearm progress toward its target."""
        target = 1.0 if self.tonearm_target else 0.0
        step = min(1.0, dt * 7.0)
        new = self.tonearm_progress + (target - self.tonearm_progress) * step
        if abs(new - self.tonearm_progress) > 0.001:
            self.tonearm_progress = new
            self.update()

    def vinyl_ring_radius(self):
        """黑胶外环半径 = 设置中的像素值（50~350 px，直接控制）。"""
        try:
            v = float(self.controller.config.get("record", {}).get("vinyl_ring_r", 120.0))
        except Exception:
            v = 120.0
        return min(350.0, max(50.0, v))

    def center(self):
        return QPointF(self.x() + self.width() / 2, self.y() + self.height() / 2)

    def set_center(self, x, y):
        self.move(int(x - self.width() / 2), int(y - self.height() / 2))

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.role == ROLE_BALLOON:
            self._paint_balloon(p)
        else:
            self._paint_circle(p)
        p.end()

    def _paint_balloon(self, p):
        """气球外观：四图切换（已设置）或蓝色随注水调透明度（默认）。"""
        r = self.radius
        rect = QRectF(3, 3, r * 2 - 6, r * 2 - 6)
        visual = self.controller.balloon_visual(self.water_pct)
        path = QPainterPath()
        path.addEllipse(rect)
        p.save()
        p.setClipPath(path)
        if visual[0] == "image":
            p.drawPixmap(rect.toRect(), QPixmap(visual[1]))
        else:
            # visual = ("color", "#3B82F6", alpha)
            c = QColor(visual[1])
            c.setAlphaF(float(visual[2]))
            p.fillRect(rect, c)
        p.restore()
        # 边框不透明度与球体一致：透明度上限 90%（注水 0–10% 均保持 90% 透明）
        opacity = max(0.10, self.water_pct / 100.0)
        alpha = max(0, min(255, int(opacity * 200)))
        p.setPen(QPen(QColor(60, 60, 60, alpha), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)
        # highlight so the balloon reads as round
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawEllipse(QPointF(r * 0.66, r * 0.6), r * 0.16, r * 0.14)

    def _paint_circle(self, p):
        r = self.radius
        c = self.width() / 2.0            # window center (ball + vinyl center)
        # 3px 内缩：球体外接矩形不得与窗口等大，否则圆在上下左右四个极点
        # 正好压在窗口边缘（含 3px 描边的半宽），抗锯齿边缘被裁剪 → 磨平
        rect = QRectF(c - r + 3, c - r + 3, r * 2 - 6, r * 2 - 6)
        path = QPainterPath()
        path.addEllipse(rect)

        rotating = self.rotation_angle != 0.0
        ring_r = self.vinyl_ring_radius() if self.role == ROLE_PET else r
        p.save()
        if rotating:
            p.translate(c, c)
            p.rotate(self.rotation_angle)
            p.translate(-c, -c)

        # 唱片模式：先画黑胶圆盘（外环），再画球体盖住中心
        if self.role == ROLE_PET:
            p.setBrush(QColor(28, 28, 30, 240))
            p.setPen(QPen(QColor(12, 12, 12, 255), 2))
            p.drawEllipse(QPointF(c, c), ring_r, ring_r)
            # 沟槽按倍数缩放分布
            for i in range(5):
                gr = r / ring_r + (1.0 - r / ring_r) * (i + 1) / 6.0
                p.setPen(QPen(QColor(120, 120, 120, 80), 1))
                p.drawEllipse(QPointF(c, c), ring_r * gr, ring_r * gr)

        if self.skin is not None:
            p.setClipPath(path)
            p.drawPixmap(rect.toRect(), self.skin)
            p.setPen(QPen(QColor(40, 40, 40, 160), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect)
        else:
            # default appearance: a plain white ball with subtle shading
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, QColor("#FFFFFF"))
            grad.setColorAt(1.0, QColor("#D6D6D6"))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(120, 120, 120, 220), 3))
            p.drawEllipse(rect)
            # soft highlight
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 150))
            p.drawEllipse(QPointF(c + r * 0.22, c - r * 0.38), r * 0.16, r * 0.16)
            # rotating marker (record state): a colored arc so spin is visible
            if rotating:
                p.setPen(QPen(QColor(255, 110, 60, 220), max(4, int(r * 0.14))))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(c - r * 0.82, c - r * 0.82, r * 1.64, r * 1.64),
                          0 * 16, 70 * 16)
                p.setPen(QPen(QColor(60, 130, 255, 220), max(4, int(r * 0.14))))
                p.drawArc(QRectF(c - r * 0.82, c - r * 0.82, r * 1.64, r * 1.64),
                          180 * 16, 70 * 16)

        p.restore()

        # 唱片模式：圆心镂空——真正透明的轴孔（参考图1）。
        # 用 DestinationOut + 不透明笔刷擦除（本构建中 CompositionMode_Clear
        # 失效：对皮肤 pixmap 不生效/写出黑色）。孔位于圆心，旋转不变。
        if self.role == ROLE_PET:
            hole_r = r * 0.16
            p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.black)          # 不透明源 → 目标完全透明
            p.drawEllipse(QPointF(c, c), hole_r, hole_r)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # 唱片针：位置更靠内侧（参考图2），带黑色药丸配重块、升降杆，
        # 唱头放大；固定不随球旋转，动画插值平滑过渡
        if self.role == ROLE_PET:
            pivot = QPointF(c + ring_r * 0.52, c - ring_r * 0.80)
            # 真实唱臂绕枢轴旋转：杆长恒定，暂停/播放两位置等距，
            # 动画沿圆弧插值（任何时刻杆长相同，播放时不会变长）
            arm_len = ring_r * 0.884
            d_off = QPointF(0.70, 0.54)   # 停机位方向（枢轴→右侧）
            d_on = QPointF(0.28, 1.04)    # 落针方向（枢轴→黑胶内圈）
            a_off = math.atan2(d_off.y(), d_off.x())
            a_on = math.atan2(d_on.y(), d_on.x())
            t = max(0.0, min(1.0, self.tonearm_progress))
            ang = a_off + (a_on - a_off) * t
            tip = QPointF(pivot.x() + arm_len * math.cos(ang),
                          pivot.y() + arm_len * math.sin(ang))
            arm_ang = math.degrees(ang)
            # 臂杆
            p.setPen(QPen(QColor(200, 200, 205), 4))
            p.drawLine(pivot, tip)
            # 配重块（黑色药丸形，位于枢轴后方）
            dx = pivot.x() - tip.x()
            dy = pivot.y() - tip.y()
            dlen = math.hypot(dx, dy) or 1.0
            cwx = pivot.x() + dx / dlen * ring_r * 0.15
            cwy = pivot.y() + dy / dlen * ring_r * 0.15
            p.save()
            p.translate(cwx, cwy)
            p.rotate(arm_ang)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(38, 38, 42))
            p.drawEllipse(QRectF(-ring_r * 0.12, -ring_r * 0.055,
                                 ring_r * 0.24, ring_r * 0.11))
            p.restore()
            # 枢轴底座 + 轴心
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(95, 95, 100, 235))
            p.drawEllipse(pivot, ring_r * 0.055, ring_r * 0.055)
            p.setBrush(QColor(210, 210, 215))
            p.drawEllipse(pivot, ring_r * 0.028, ring_r * 0.028)
            # 唱头（放大，沿臂方向）+ 唱针尖
            p.save()
            p.translate(tip)
            p.rotate(arm_ang)
            p.setPen(QPen(QColor(90, 90, 95), 1))
            p.setBrush(QColor(165, 165, 170))
            p.drawRoundedRect(QRectF(-ring_r * 0.10, -ring_r * 0.055,
                                     ring_r * 0.20, ring_r * 0.11),
                              ring_r * 0.03, ring_r * 0.03)
            p.setPen(QPen(QColor(30, 30, 35), 2))
            p.drawLine(QPointF(ring_r * 0.10, 0),
                       QPointF(ring_r * 0.145, ring_r * 0.02))
            p.restore()

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = (e.globalPosition(), e.timestamp() if hasattr(e, "timestamp") else 0)
            self._dragging = True
            if self.role == ROLE_BASKET:
                self.controller.on_slingshot_start(self, e.globalPosition())
            elif self.role == ROLE_PET:
                # 单击唱片球：收起切歌面板
                self.controller._hide_record_panel()
        e.accept()

    def enterEvent(self, e):
        if self.role == ROLE_PET:
            self.controller.on_record_hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.role == ROLE_PET:
            self.controller.on_record_hover(False)
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging and self._drag_start is not None:
            if self.role == ROLE_BASKET:
                start = self._drag_start[0]
                dx = start.x() - e.globalPosition().x()
                dy = start.y() - e.globalPosition().y()
                self.controller.on_slingshot_drag(self, dx, dy)
            elif self.role == ROLE_PET or self.role == ROLE_BALLOON:
                start = self._drag_start[0]
                delta = e.globalPosition() - start
                self.move(self.x() + int(delta.x()), self.y() + int(delta.y()))
                self._drag_start = (e.globalPosition(), self._drag_start[1])
                if self.role == ROLE_BALLOON:
                    self.controller.on_balloon_dragged(self)
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_start is not None:
            if self.role == ROLE_BASKET:
                start, t0 = self._drag_start
                dx = start.x() - e.globalPosition().x()
                dy = start.y() - e.globalPosition().y()
                dist = math.hypot(dx, dy)
                is_click = dist < 6.0
                self.controller.on_slingshot_release(self, dx, dy, is_click)
            elif self.role == ROLE_BALLOON:
                self.controller.on_balloon_release(self)
        self._drag_start = None
        self._dragging = False
        e.accept()

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        self.controller.build_context_menu(menu, self)
        menu.exec(e.globalPos())
        e.accept()

    def mouseDoubleClickEvent(self, e):
        """双击：唱片状态=播放/暂停；气球=爆炸。"""
        if e.button() == Qt.LeftButton:
            if self.role == ROLE_PET:
                self.controller.on_record_double_click()
            elif self.role == ROLE_BALLOON:
                self.controller.on_balloon_explode(self)
        e.accept()
