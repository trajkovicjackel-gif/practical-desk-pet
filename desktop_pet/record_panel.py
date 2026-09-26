# -*- coding: utf-8 -*-
"""切歌面板：唱片模式下悬停 3 秒呼出的横向工具条。

第一行控件：上一首 / 下一首 / 暂停播放 / 开始播放 / 音量滑条。
第二行：播放进度条（拖动调节进度，步长 1 秒）+ 当前时间/总时长 (mm:ss)。
每个操作同时向系统发送对应媒体键，可同步影响外部音乐播放软件。
"""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
                               QSlider, QLabel)

import os


def _fmt(ms):
    sec = max(0, int(ms // 1000))
    return f"{sec // 60:02d}:{sec % 60:02d}"


class RecordPanel(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._dragging = False
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(470, 106)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(5)

        row1 = QHBoxLayout()
        row1.setSpacing(4)

        def btn(text, slot):
            b = QPushButton(text)
            b.setFixedHeight(28)
            b.setStyleSheet(
                "QPushButton { background: rgba(40,40,50,220); color: white;"
                " border: 1px solid rgba(255,255,255,60); border-radius: 6px;"
                " padding: 0 8px; font: 11px 'Microsoft YaHei'; }"
                "QPushButton:hover { background: rgba(70,70,90,240); }")
            b.clicked.connect(slot)
            return b

        row1.addWidget(btn("上一首", self.controller.record_prev))
        row1.addWidget(btn("下一首", self.controller.record_next))
        row1.addWidget(btn("暂停", self.controller.record_toggle_pause))
        row1.addWidget(btn("播放", self.controller.record_play))

        vol_label = QLabel("音量")
        vol_label.setStyleSheet("color: white; font: 10px 'Microsoft YaHei';")
        row1.addWidget(vol_label)
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,80); }"
            "QSlider::handle:horizontal { width: 10px; margin: -4px 0;"
            " background: #FFB74D; border-radius: 5px; }")
        # 音量 0..100 线性映射到 0..100%（修复左半区恒为 0%）
        self.vol_slider.valueChanged.connect(self.controller.record_set_volume)
        row1.addWidget(self.vol_slider)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.time_cur = QLabel("00:00")
        self.time_total = QLabel("00:00")
        for l in (self.time_cur, self.time_total):
            l.setStyleSheet("color: rgba(255,255,255,220); font: 10px 'Consolas';")
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setRange(0, 0)
        self.progress.setSingleStep(1)
        self.progress.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: rgba(255,255,255,80);"
            " border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #FFB74D; border-radius: 3px; }"
            "QSlider::handle:horizontal { width: 12px; margin: -4px 0;"
            " background: #FFD54F; border-radius: 6px; }")
        self.progress.sliderPressed.connect(self._on_press)
        self.progress.sliderReleased.connect(self._on_release)
        self.progress.sliderMoved.connect(self._on_move)
        row2.addWidget(self.time_cur)
        row2.addWidget(self.progress, 1)
        row2.addWidget(self.time_total)
        outer.addLayout(row2)

        # 第三行：当前播放的歌曲/视频标题（进度条下方）
        self._last_title = ""
        self.title_label = QLabel("")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            "color: rgba(255,255,255,210); font: 10px 'Microsoft YaHei';")
        self.title_label.setWordWrap(False)
        outer.addWidget(self.title_label)

        self._attached = None      # 当前连接的 QMediaPlayer（None = 未连接）
        self.attach_player(controller.music_player)

    def set_external_title(self, title):
        """显示外部播放器当前曲目/视频标题（同步模式）。"""
        title = (title or "").strip()
        if title and title != self._last_title:
            self._last_title = title
            self.title_label.setText(title[:46])

    def set_local_title(self, path):
        """显示本地播放曲目名（文件名）。"""
        name = os.path.basename(path) if path else ""
        if name != self._last_title:
            self._last_title = name
            self.title_label.setText(name[:46])

    def set_volume_slider(self, value):
        """外部同步：把音量滑条对齐到当前系统音量（不发信号防回环）。"""
        self.vol_slider.blockSignals(True)
        self.vol_slider.setValue(max(0, min(100, int(value))))
        self.vol_slider.blockSignals(False)

    # ------------------------------------------------------------- progress
    def attach_player(self, player):
        """连接到当前本地播放器（播放器可能是在面板创建后才创建）。
        重复连接同一播放器是无害的（信号会重复触发但值相同）。"""
        if player is None or player is self._attached:
            return
        if self._attached is not None:
            try:
                self._attached.positionChanged.disconnect(self._on_position)
                self._attached.durationChanged.disconnect(self._on_duration)
            except (RuntimeError, TypeError):
                pass
        self._attached = player
        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(self._on_duration)

    def sync_progress(self):
        """每帧兜底刷新：即使信号丢失也能实时反映播放进度。
        同步外部模式禁用（进度条由外部轮询驱动，避免与本地播放器抢位）。"""
        if self.controller._sync_on():
            return
        player = self.controller.music_player
        if player is None or self._dragging:
            return
        if player is not self._attached:
            self.attach_player(player)
        pos = player.position()
        dur = player.duration()
        if dur > 0 and dur != self.progress.maximum() * 1000:
            self._on_duration(dur)
        if pos > 0 or dur > 0:
            self._on_position(pos)

    def _on_duration(self, ms):
        if self.controller._sync_on():
            return
        total_sec = max(0, int(ms // 1000))
        self.time_total.setText(_fmt(ms))
        if not self._dragging:
            # 死区：时长仅 ±1s 抖动时不重设范围（防止滑块闪烁）
            if abs(total_sec - self.progress.maximum()) >= 2 \
                    or total_sec < self.progress.value():
                self.progress.setRange(0, total_sec)

    def _on_position(self, ms):
        if self.controller._sync_on():
            return
        if not self._dragging:
            self.time_cur.setText(_fmt(ms))
            total = self.progress.maximum()
            cur = max(0, int(ms // 1000))
            if 0 <= cur <= total:
                self.progress.setValue(cur)

    def _on_press(self):
        self._dragging = True

    def _on_move(self, sec):
        self.time_cur.setText(_fmt(sec * 1000))

    def _on_release(self):
        self._dragging = False
        sec = self.progress.value()
        if self.controller._sync_on():
            # 同步外部模式：跳转外部播放器进度（SMTC）
            self.controller.smtc_seek(sec)
            return
        player = self.controller.music_player
        if player is not None:
            player.setPosition(sec * 1000)

    def sync_external_progress(self, playing, pos_ms, dur_ms):
        """显示外部播放器（SMTC）的实时进度；拖动过程中不抢滑块。"""
        if dur_ms > 0:
            total = max(0, int(dur_ms // 1000))
            # 死区：时长 ±1s 抖动 / 会话切换时避免滑块闪烁
            if abs(total - self.progress.maximum()) >= 2 \
                    or total < self.progress.value():
                self.progress.setRange(0, total)
            self.time_total.setText(_fmt(dur_ms))
        if not self._dragging:
            cur = max(0, int(pos_ms // 1000))
            if 0 <= cur <= self.progress.maximum():
                self.progress.setValue(cur)
            self.time_cur.setText(_fmt(pos_ms))

    def position_below(self, ball_window):
        x = ball_window.x() + ball_window.width() // 2 - self.width() // 2
        y = ball_window.y() + ball_window.height() + 6
        self.move(max(0, x), max(0, y))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 160), 1))
        p.setBrush(QColor(24, 24, 32, 220))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        p.end()
