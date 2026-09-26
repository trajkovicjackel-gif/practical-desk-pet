# -*- coding: utf-8 -*-
"""Desktop Pet controller: mode manager, game loops, scoring, tray."""

import ctypes
import math
import os
import random
import time
from collections import deque

from PySide6.QtCore import Qt, QTimer, QObject, Signal, QPointF, QRectF, QUrl
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import QWidget, QMenu, QSystemTrayIcon

from . import physics
from .config import load, save, config_dir
from . import desktop_icons as desk
from .pet_window import PetWindow, ROLE_PET, ROLE_PONG, ROLE_BASKET, ROLE_BALLOON
from .platforms import PlatformWindow, PLATFORM_W, PLATFORM_H
from .overlay import OverlayWindow
from .score_label import ScoreLabel
from .settings_dialog import SettingsDialog
from . import recycle as recycle_mod

VK_LEFT = 0x25
VK_RIGHT = 0x27


def _key_down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

MODE_IDLE = "idle"
MODE_PONG = "pong"
MODE_BASKETBALL = "basketball"
MODE_BALLOON = "balloon"

TICK_MS = 16
PONG_BALL_SPEED = 340
SLINGSHOT_K = 9.0
SLAP_IMPULSE = 1100.0
HOOP_SCORE = 3
HOOP_RADIUS = 60          # scoring radius around the real Recycle Bin icon
HOOP_COOLDOWN_MS = 1600
VK_SPACE = 0x20

# 弹珠模式 AI 平台难度（5 档）：速度 (px/s) + 落点预测
DIFFICULTY = {
    "bean":   {"speed": 180, "predictive": False},   # 豆包
    "simple": {"speed": 280, "predictive": False},   # 简单
    "normal": {"speed": 420, "predictive": False},   # 正常
    "hell":   {"speed": 620, "predictive": True},    # 地狱
    "king":   {"speed": 950, "predictive": True},    # 王者
}
DIFFICULTY_LABELS = {
    "bean": "豆包", "simple": "简单", "normal": "正常",
    "hell": "地狱", "king": "王者",
}

# 弹珠/气球模式显示名
MODE_LABELS = {
    MODE_IDLE: "唱片模式",
    MODE_PONG: "弹珠模式",
    MODE_BASKETBALL: "篮球模式",
    MODE_BALLOON: "气球模式",
}


class PetApp:
    def __init__(self, qapp):
        self.qapp = qapp
        self.config = load()
        self.field = self._field()
        # 每次启动默认进入唱片（待机）状态，不恢复上次关闭时的模式
        self.mode = MODE_IDLE

        self.overlay = None
        self.platform_top = None
        self.platform_bottom = None
        self.score_label = None
        self.ball_windows = []      # pong/basketball ball windows
        self.balloon_windows = []   # balloon windows
        self.idle_window = None
        self.settings = None
        self.tray = None

        self.pong = None            # physics.PongState
        self.basket = None          # physics.Ball
        self.sling = None           # (start_pos, last_dx, last_dy)
        self.hoop_enabled = False
        self.hoop_pos = None        # (cx, cy) of the real Recycle Bin icon
        self.hoop_cooldown_until = 0
        self._trail = None
        self.calib_window = None
        self.hidden = False
        self.keys = {"left": False, "right": False}
        self._space_down_prev = False       # edge detection for SPACE slap
        self._pong_pending = 0              # staggered respawn counter
        self._pong_next_spawn = 0.0
        self._record_playing = False
        self._record_angle = 0.0
        self._record_index = 0
        self.music_player = None
        self.music_audio = None
        self.record_panel = None
        self._title_bridge = _TitleBridge()
        self._title_bridge.title_ready.connect(self._apply_external_title)
        self.record_hover_timer = QTimer()
        self.record_hover_timer.setSingleShot(True)
        self.record_hover_timer.timeout.connect(self._show_record_panel)
        self._balloon_effects = []          # explosion visual effects
        self.launch_player = None
        self.launch_audio = None

        self.timer = QTimer()
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._key_sink = QWidget()

        self._build_tray()
        self._build_score_label()

        # 启动总是进入唱片（待机）状态
        self.switch_mode(MODE_IDLE)

        # FFmpeg 多媒体后端首次实例偶发冻结（PlayingState 但不走时钟）：
        # 启动时用一个一次性播放器消耗掉首个实例，保证后续播放正常
        self._warmup_audio()

        # 外部播放器选择（同步模式）
        try:
            from . import smtc
            smtc.set_selected(
                self.config.get("record", {}).get("external_session", "auto"))
        except Exception:
            pass

    def _warmup_audio(self):
        try:
            w = QMediaPlayer()
            wa = QAudioOutput()
            w.setAudioOutput(wa)
            src = self.config["basketball"].get("launch_sound")
            if src and not os.path.isabs(src):
                from .config import resolve_path
                src = resolve_path(src)
            if src and os.path.exists(src):
                w.setSource(QUrl.fromLocalFile(src))
                w.play()
            QTimer.singleShot(700, lambda: self._warmup_cleanup(w, wa))
        except Exception:
            pass

    def _warmup_cleanup(self, w, wa):
        try:
            w.stop()
            w.setSource(QUrl())
            w.deleteLater()
            wa.deleteLater()
        except Exception:
            pass

    # ------------------------------------------------------------- geometry
    def _field(self):
        """Work area = primary screen minus taskbar (any side)."""
        geo = self.qapp.primaryScreen().availableGeometry()
        return (geo.x(), geo.y(), geo.width(), geo.height())

    def _basketball_field(self):
        """Basketball field: full display; bottom raised only by a VISIBLE
        bottom taskbar. Side taskbars and auto-hidden taskbars are ignored."""
        screen = self.qapp.primaryScreen().geometry()
        work = self.qapp.primaryScreen().availableGeometry()
        return desk.basketball_field(
            (screen.x(), screen.y(), screen.width(), screen.height()),
            (work.x(), work.y(), work.width(), work.height()))

    # ------------------------------------------------------------ shortcuts
    # Left/Right state is polled per tick via GetAsyncKeyState (works without
    # window focus, no threads, no hooks).

    # ---------------------------------------------------------------- tray
    def _add_menu_mode_actions(self, menu):
        """模式切换菜单项（返回 {mode: action}）。"""
        acts = {}
        for mode in (MODE_IDLE, MODE_PONG, MODE_BASKETBALL, MODE_BALLOON):
            act = menu.addAction(MODE_LABELS[mode])
            act.setCheckable(True)
            act.setChecked(mode == self.mode)
            act.triggered.connect(lambda _c, m=mode: self.switch_mode(m))
            acts[mode] = act
        return acts

    def _add_menu_tail(self, menu):
        """隐藏/设置/退出（托盘菜单与右键菜单共用）。"""
        menu.addSeparator()
        hide_act = menu.addAction("显示桌面悬浮" if self.hidden else "隐藏桌面悬浮")
        hide_act.triggered.connect(self.toggle_hidden)
        settings = menu.addAction("设置…")
        settings.triggered.connect(self.open_settings)
        menu.addSeparator()
        quit_act = menu.addAction("退出")
        quit_act.triggered.connect(self.qapp.quit)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(QIcon(self._tray_pixmap()), self._key_sink)
        self.tray.setToolTip("桌面悬浮桌宠")
        menu = QMenu()
        self.mode_actions = self._add_menu_mode_actions(menu)
        self._add_menu_tail(menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._sync_mode_actions()

    def _tray_pixmap(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        # white ball to match the default pet appearance
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QColor("#8A8A8A"))
        p.drawEllipse(QRectF(4, 4, 56, 56))
        p.setBrush(QColor(230, 230, 230))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(40, 34), 9, 9)
        p.end()
        return pm

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_settings()

    def _sync_mode_actions(self):
        for mode, act in self.mode_actions.items():
            act.setChecked(mode == self.mode)

    # ------------------------------------------------------------ score ui
    def _build_score_label(self):
        self.score_label = ScoreLabel()
        fx, fy, fw, fh = self.field
        self.score_label.move(fx + fw - 220, fy + 6)

    def _update_score_label(self):
        if self.mode == MODE_PONG:
            self.score_label.set_score(f"弹珠得分：{self.config['pong']['score']}")
            self.score_label.show()
        elif self.mode == MODE_BASKETBALL:
            self.score_label.set_score(f"篮球得分：{self.config['basketball']['score']}")
            self.score_label.show()
        elif self.mode == MODE_BALLOON:
            self.score_label.set_score(f"气球得分：{self.config['balloon'].get('score', 0)}")
            self.score_label.show()
        else:
            self.score_label.hide()

    # -------------------------------------------------------------- modes
    def switch_mode(self, mode):
        if mode not in (MODE_IDLE, MODE_PONG, MODE_BASKETBALL, MODE_BALLOON):
            return
        # 离开唱片模式：停止音乐、收起切歌面板
        if self.mode == MODE_IDLE and mode != MODE_IDLE:
            if self.music_player is not None:
                self.music_player.stop()
            self._record_playing = False
            self.record_hover_timer.stop()
            self._hide_record_panel()
        self._clear_windows()
        self.mode = mode
        self.config["mode"] = mode
        save(self.config)
        self._sync_mode_actions()

        if mode == MODE_IDLE:
            self._enter_idle()
        elif mode == MODE_PONG:
            self._enter_pong()
        elif mode == MODE_BASKETBALL:
            self._enter_basketball()
        elif mode == MODE_BALLOON:
            self._enter_balloon()
        self._update_score_label()

    def _clear_windows(self):
        for w in self.ball_windows:
            w.close()
        self.ball_windows = []
        if self.platform_top:
            self.platform_top.close()
            self.platform_top = None
        if self.platform_bottom:
            self.platform_bottom.close()
            self.platform_bottom = None
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        for win in self.balloon_windows:
            win.close()
        self.balloon_windows = []
        if self.idle_window:
            self.idle_window.close()
            self.idle_window = None
        self._hide_record_panel()
        self.pong = None
        self.basket = None
        self.sling = None
        self._trail = None

    def _make_window(self, role):
        w = PetWindow(self, role=role, radius=self.config["appearance"]["radius"])
        skin = self.config["appearance"].get("skin_path")
        if skin:
            w.apply_appearance(self.config["appearance"]["radius"], skin)
        w.show()
        return w

    # -------------------------------------------------------------- record
    def _record_window_size(self):
        r = self.config["appearance"]["radius"]
        ring_r = self._vinyl_ring_r()
        # 窗口至少容纳球体与黑胶外环 + 唱臂（含配重/唱头）
        side = int(max(r * 2, ring_r * 2.75))
        return side

    def _vinyl_ring_r(self):
        try:
            v = float(self.config.get("record", {}).get("vinyl_ring_r", 120.0))
        except (TypeError, ValueError):
            v = 120.0
        return min(350.0, max(50.0, v))

    def _enter_idle(self):
        fx, fy, fw, fh = self.field
        self.idle_window = self._make_window(ROLE_PET)
        side = self._record_window_size()
        self.idle_window.resize(side, side)
        self.idle_window.set_center(fx + fw / 2, fy + fh / 2)
        # 进入唱片模式时保持旋转状态（若正在播放）
        if self._record_playing:
            self.idle_window.set_rotation(self._record_angle)
        self.idle_window.set_tonearm_engaged(self._record_playing)
        # 唱片针初始位置直接到位（避免启动时的过渡动画）
        self.idle_window.tonearm_progress = 1.0 if self._record_playing else 0.0

    def balloon_visual(self, water_pct):
        """气球外观：用户设置了四图则按 0/25/50/100% 切换；否则统一蓝色。

        默认外观透明度上限 90%：注水 0–10% 均保持 90% 透明（不透明度 10%），
        注水 100% 时透明度 0%（不透明度 100%），线性过渡。
        """
        images = (self.config.get("balloon", {}).get("images") or [None] * 4)
        if any(images):
            if water_pct >= 75:
                i = 3
            elif water_pct >= 37.5:
                i = 2
            elif water_pct >= 12.5:
                i = 1
            else:
                i = 0
            path = images[i] if i < len(images) else None
            if path and os.path.exists(path):
                return ("image", path)
        # 默认：蓝色，不透明度 = max(10%, 注水%)（透明度上限 90%）
        alpha = max(0.10, min(1.0, water_pct / 100.0))
        return ("color", "#3B82F6", alpha)

    def _record_tracks(self):
        """有效歌曲列表：优先歌单，其次单曲。"""
        rec = self.config.get("record", {})
        tracks = [t for t in rec.get("playlist", []) if t and os.path.exists(t)]
        single = rec.get("audio_path")
        if not tracks and single and os.path.exists(single):
            tracks = [single]
        return tracks

    def _sync_on(self):
        return bool(self.config.get("record", {}).get("sync_external", True))

    def _play_record_index(self, idx):
        """本地播放指定索引的歌曲（同步外部模式不读取歌单、不本地播放）。"""
        if self._sync_on():
            return
        tracks = self._record_tracks()
        if not tracks:
            return
        idx = idx % len(tracks)
        self._record_index = idx
        if self.music_player is None:
            self.music_player = QMediaPlayer()
            self.music_audio = QAudioOutput()
            self.music_player.setAudioOutput(self.music_audio)
            self.music_player.mediaStatusChanged.connect(self._on_record_status)
            self._attach_panel_to_player()
        self.music_player.stop()
        self.music_player.setSource(QUrl.fromLocalFile(tracks[idx]))
        self.music_player.play()
        self._record_playing = True
        if self.record_panel is not None:
            self.record_panel.set_local_title(tracks[idx])
        # FFmpeg 后端首次播放偶发不启动：媒体加载完成后若仍未播放则重试一次
        if getattr(self, "_ensure_hooked", False):
            try:
                self.music_player.mediaStatusChanged.disconnect(self._ensure_playing)
            except Exception:
                pass
        self._ensure_hooked = True
        self.music_player.mediaStatusChanged.connect(self._ensure_playing)
        if self.idle_window is not None:
            self.idle_window.set_rotation(self._record_angle)
            self.idle_window.set_tonearm_engaged(True)

    def _ensure_playing(self, status):
        """媒体加载完成但播放器未进入播放状态时，补发一次 play()。"""
        if status not in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            return
        if getattr(self, "_ensure_hooked", False):
            try:
                self.music_player.mediaStatusChanged.disconnect(self._ensure_playing)
            except Exception:
                pass
            self._ensure_hooked = False
        if self._record_playing and self.music_player is not None and \
                self.music_player.playbackState() != QMediaPlayer.PlayingState:
            self.music_player.play()

    def _attach_panel_to_player(self):
        if self.record_panel is not None:
            self.record_panel.attach_player(self.music_player)

    def _set_playing(self, playing):
        """统一切换播放状态与唱臂动画；暂停时保留当前旋转角度（不回正）。"""
        self._record_playing = bool(playing)
        if self.idle_window is not None:
            self.idle_window.set_rotation(self._record_angle)
            self.idle_window.set_tonearm_engaged(playing)

    def _on_record_status(self, status):
        """一首歌结束（仅本地模式）：按播放模式决定下一首。"""
        if self._sync_on():
            return
        if status != QMediaPlayer.EndOfMedia:
            return
        rec = self.config.get("record", {})
        tracks = self._record_tracks()
        if not tracks:
            return
        if not rec.get("auto_next", True):
            self._set_playing(False)
            return
        mode = rec.get("playback_mode", "list_loop")
        n = len(tracks)
        if mode == "single_loop":
            nxt = self._record_index
        elif mode == "sequential":
            nxt = self._record_index + 1
            if nxt >= n:                      # 顺序播放到结尾即停止
                self._set_playing(False)
                return
        elif mode == "shuffle":
            nxt = random.choice([i for i in range(n) if i != self._record_index]) \
                if n > 1 else self._record_index
        else:                                 # list_loop
            nxt = (self._record_index + 1) % n
        self._play_record_index(nxt)

    def on_record_double_click(self):
        """双击唱片：播放/暂停（暂停后再次双击从上次位置续播）。"""
        if self._record_playing:
            # 停止/暂停：保留播放进度位置，唱片保持当前旋转角度（不回正）
            self._record_playing = False
            if self._sync_on():
                self._send_media_key(self.VK_MEDIA_PLAY_PAUSE)
            elif self.music_player is not None:
                self.music_player.pause()
            if self.idle_window is not None:
                self.idle_window.set_rotation(self._record_angle)
                self.idle_window.set_tonearm_engaged(False)
            return
        if self._sync_on():
            # 同步外部模式：不读取本地歌单，只发媒体键并驱动动画
            self._send_media_key(self.VK_MEDIA_PLAY_PAUSE)
            self._record_playing = True
            if self.idle_window is not None:
                self.idle_window.set_tonearm_engaged(True)
            return
        # 本地模式：已有曲目且处于暂停/停止 → 从上次位置续播
        if self.music_player is not None and self.music_player.source() \
                and self.music_player.playbackState() != QMediaPlayer.PlayingState:
            self.music_player.play()
            self._record_playing = True
            if self.idle_window is not None:
                self.idle_window.set_tonearm_engaged(True)
            return
        tracks = self._record_tracks()
        if not tracks:
            return
        self._play_record_index(self._record_index if hasattr(self, "_record_index") else 0)

    # ---- 切歌面板操作 ----
    VK_MEDIA_NEXT = 0xB0
    VK_MEDIA_PREV = 0xB1
    VK_MEDIA_PLAY_PAUSE = 0xB3
    VK_VOLUME_UP = 0xAF
    VK_VOLUME_DOWN = 0xAE

    def _send_media_key(self, vk):
        """仅当「同步外部音乐软件」开启时发送系统媒体键。"""
        if not self._sync_on():
            return
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(vk, 0, 0, 0)
            user32.keybd_event(vk, 0, 2, 0)   # KEYEVENTF_KEYUP
        except Exception:
            pass

    def record_prev(self):
        if self._sync_on():
            self._send_media_key(self.VK_MEDIA_PREV)
            return
        tracks = self._record_tracks()
        if tracks:
            self._play_record_index(self._record_index - 1)

    def record_next(self):
        if self._sync_on():
            self._send_media_key(self.VK_MEDIA_NEXT)
            return
        tracks = self._record_tracks()
        if tracks:
            self._play_record_index(self._record_index + 1)

    def record_toggle_pause(self):
        """暂停按钮：同步模式只发媒体键；本地模式暂停/续播。"""
        if self._sync_on():
            if self._record_playing:
                self._send_media_key(self.VK_MEDIA_PLAY_PAUSE)
                self._set_playing(False)
            return
        if self.music_player is not None:
            if self.music_player.playbackState() == QMediaPlayer.PlayingState:
                self.music_player.pause()
                self._set_playing(False)
            elif self.music_player.source():
                self.music_player.play()
                self._set_playing(True)
        else:
            tracks = self._record_tracks()
            if tracks:
                self._play_record_index(getattr(self, "_record_index", 0))

    def record_play(self):
        """播放按钮：同步模式只发媒体键；本地模式从上次位置续播。"""
        if self._sync_on():
            if not self._record_playing:
                self._send_media_key(self.VK_MEDIA_PLAY_PAUSE)
                self._set_playing(True)
            return
        tracks = self._record_tracks()
        if self.music_player is not None and self.music_player.source() \
                and not self._record_playing:
            self.music_player.play()
            self._set_playing(True)
        elif self.music_player is None and tracks:
            self._play_record_index(getattr(self, "_record_index", 0))

    # ---- 音量 ----
    # 本地：QAudioOutput.setVolume 范围是 0.0~1.0，按 0..100 线性换算；
    # 同步外部：实时（节流）发送系统音量键，作用于所有外部播放器
    def record_set_volume(self, pct):
        if self._sync_on():
            self._send_external_volume(int(pct))
        elif self.music_audio is not None:
            self.music_audio.setVolume(max(0.0, min(1.0, int(pct) / 100.0)))

    def _send_external_volume(self, pct):
        """同步外部模式音量：绝对设置系统主音量（0-100 全覆盖），
        不可用时回退为节流发送相对音量键。"""
        fraction = max(0.0, min(1.0, int(pct) / 100.0))
        try:
            from . import sysvolume
            if sysvolume.set(fraction):
                self._vol_last = int(pct)
                self._vol_last_t = time.monotonic()
                return
        except Exception:
            pass
        # 兜底：按滑块差值节流发送系统音量键（100ms 内最多一批）
        now = time.monotonic()
        if now - getattr(self, "_vol_last_t", 0.0) < 0.10:
            return
        last = getattr(self, "_vol_last", None)
        if last is None:
            last = 80
        delta = pct - last
        self._vol_last = pct
        self._vol_last_t = now
        if delta == 0:
            return
        steps = min(3, max(1, abs(delta) // 6))
        vk = self.VK_VOLUME_UP if delta > 0 else self.VK_VOLUME_DOWN
        for _ in range(steps):
            self._send_media_key(vk)

    def smtc_seek(self, sec):
        """同步外部模式：跳转外部播放器进度（SMTC→UIA→物理拖拽三级方案）。

        seek 内部含位置验证轮询，可能阻塞数秒 → 放入后台线程执行。
        """
        try:
            from . import smtc
            import threading
            threading.Thread(target=smtc.seek, args=(float(sec),),
                             daemon=True).start()
        except Exception:
            pass

    def _hide_record_panel(self):
        if self.record_panel is not None:
            self.record_panel.hide()

    def _show_record_panel(self):
        if self.record_panel is None:
            from .record_panel import RecordPanel
            self.record_panel = RecordPanel(self)
        self._attach_panel_to_player()
        if self.idle_window is not None:
            self.record_panel.position_below(self.idle_window)
        # 同步模式：音量滑条对齐当前系统主音量（绝对控制）
        if self._sync_on():
            try:
                from . import sysvolume
                v = sysvolume.get()
            except Exception:
                v = None
            if v is not None:
                self.record_panel.set_volume_slider(int(round(v * 100)))
                self._vol_last = int(round(v * 100))
        self.record_panel.show()

    def on_record_hover(self, hovering):
        """鼠标停留球上 3 秒呼出切歌面板；离开不收起，仅单击球体收起。"""
        if self.record_hover_timer is not None:
            self.record_hover_timer.stop()
        if hovering:
            self.record_hover_timer.start(3000)

    # -------------------------------------------------------------- pong
    def _enter_pong(self):
        fx, fy, fw, fh = self.field
        self.platform_top = PlatformWindow(fx + fw / 2 - PLATFORM_W / 2, fy + 14, "top")
        self.platform_bottom = PlatformWindow(fx + fw / 2 - PLATFORM_W / 2, fy + fh - 14 - PLATFORM_H, "bottom")
        self.pong = physics.PongState(field=self.field)
        self.spawn_balls()

    def spawn_balls(self):
        if self.mode != MODE_PONG:
            return
        count = min(10, int(self.config["pong"]["ball_count"]))
        base_speed = int(self.config["pong"].get("ball_speed", PONG_BALL_SPEED))
        fx, fy, fw, fh = self.field
        r = self.config["appearance"]["radius"]
        # remove old ball windows
        for w in self.ball_windows:
            w.close()
        self.ball_windows = []
        self.pong.balls = []
        for _ in range(count):
            # 全部在屏幕中央水平分割线上发射，方向（角度）完全随机
            b = physics.Ball(
                x=fx + fw * random.uniform(0.12, 0.88),
                y=fy + fh / 2,
                r=r, vx=0.0, vy=0.0)
            ang = random.uniform(-math.pi, math.pi)
            speed = base_speed * random.uniform(0.85, 1.15)
            b.vx = speed * math.cos(ang)
            b.vy = speed * math.sin(ang)
            self.pong.balls.append(b)
            win = self._make_window(ROLE_PONG)
            win.set_center(b.x, b.y)
            self.ball_windows.append(win)

    def _spawn_one_pong_ball(self):
        """Spawn a single extra pong ball on the center line, random angle."""
        if self.pong is None:
            return
        base_speed = int(self.config["pong"].get("ball_speed", PONG_BALL_SPEED))
        fx, fy, fw, fh = self.field
        r = self.config["appearance"]["radius"]
        x = fx + fw * random.uniform(0.12, 0.88)
        y = fy + fh / 2                      # 中央水平分割线
        ang = random.uniform(-math.pi, math.pi)
        speed = base_speed * random.uniform(0.85, 1.15)
        b = physics.Ball(x=x, y=y, r=r,
                         vx=speed * math.cos(ang), vy=speed * math.sin(ang))
        self.pong.balls.append(b)
        win = self._make_window(ROLE_PONG)
        win.set_center(b.x, b.y)
        self.ball_windows.append(win)

    def respawn_balls(self):
        if self.mode == MODE_PONG:
            self.spawn_balls()
        elif self.mode == MODE_BASKETBALL:
            self._reset_basketball_ball()
        self._update_score_label()

    # ---------------------------------------------------------- basketball
    def _enter_basketball(self):
        self.overlay = OverlayWindow(self._basketball_field())
        self.overlay.show()
        self._trail = deque(maxlen=36)

        # real desktop Recycle Bin is the hoop target; the user calibrates it
        # by clicking the real icon (auto-prompted on first interaction)
        pos = self.config["basketball"].get("hoop_pos")
        calibrated = bool(self.config["basketball"].get("hoop_calibrated"))
        self.hoop_pos = (int(pos[0]), int(pos[1])) if pos and calibrated else None
        # 校准点击即为最可信依据（回收站可见性检测可能不可靠）
        self.hoop_enabled = calibrated and self.hoop_pos is not None
        # 仅在「尚未校准」时提示一次；校准后不再重复弹出校准提示
        if not calibrated:
            self._calib_log(
                f"_enter_basketball toast: calibrated={calibrated} "
                f"pos={pos} bin_visible={recycle_mod.recycle_bin_visible_on_desktop()}")
            if recycle_mod.recycle_bin_visible_on_desktop():
                self.tray.showMessage(
                    "桌面悬浮桌宠", "请先校准回收站位置：拍打或拖拽篮球后将自动弹出校准窗口。",
                    QSystemTrayIcon.Information, 4000)
            else:
                self.tray.showMessage(
                    "桌面悬浮桌宠", "未检测到桌面回收站，篮球模式无法投篮计分。",
                    QSystemTrayIcon.Information, 4000)

        self._reset_basketball_ball()

    def _calib_log(self, msg):
        """校准事件诊断日志（%APPDATA%/DesktopPet/calib.log）。"""
        try:
            import datetime
            p = os.path.join(config_dir(), "calib.log")
            with open(p, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().strftime('%H:%M:%S')} {msg}\n")
        except Exception:
            pass

    # ------------------------------------------------- hoop calibration
    def start_calibration(self):
        """Full-screen click catcher: the user clicks their real Recycle Bin
        icon; that point becomes the hoop target and is persisted."""
        if self.calib_window is not None:
            return
        self._calib_log("start_calibration (catcher opened)")
        win = _CalibrationWindow(self)
        win.setGeometry(QRectF(*self._basketball_field()).toRect())
        win.show()
        self.calib_window = win
        # hide gameplay windows while calibrating
        for w in self.ball_windows:
            w.hide()
        if self.overlay:
            self.overlay.hide()

    def _restore_gameplay_windows(self):
        """校准结束后恢复被隐藏的游戏窗口（左键/右键取消共用）。"""
        for w in self.ball_windows:
            w.show()
        if self.overlay:
            self.overlay.show()

    def _on_calibration_click(self, gpos):
        if self.calib_window is None:
            return
        x, y = int(gpos.x()), int(gpos.y())
        self.config["basketball"]["hoop_pos"] = [x, y]
        self.config["basketball"]["hoop_calibrated"] = True
        save(self.config)
        self.hoop_pos = (x, y)
        self.hoop_enabled = True   # 用户已点击真实回收站图标，视为校准成功
        self._calib_log(f"calibration click saved: ({x}, {y})")
        self._close_calibration()
        # 设置面板可能已在更早创建：立即刷新“回收站篮筐”显示值
        if self.settings is not None:
            try:
                self.settings.refresh_hoop_label()
            except Exception:
                pass
        self.tray.showMessage(
            "篮球模式", f"回收站篮筐已校准：({x}, {y})",
            QSystemTrayIcon.Information, 2500)
        self._restore_gameplay_windows()

    def _close_calibration(self):
        if self.calib_window is not None:
            self.calib_window.close()
            self.calib_window = None

    def _reset_hoop_calibration(self):
        """清除已保存的回收站位置，要求用户重新校准。"""
        self._calib_log("reset_hoop_calibration (user action)")
        self.config["basketball"]["hoop_calibrated"] = False
        self.config["basketball"]["hoop_pos"] = None
        save(self.config)
        self.hoop_pos = None
        self.hoop_enabled = False
        if self.settings is not None:
            self.settings.refresh_hoop_label()

    # ------------------------------------------------- bar seek (no calibration)
    # 进度条跳转由 smtc.seek 三级方案完成：SMTC → UIA → 实时像素扫描拖拽
    # （每次 seek 自动定位播放器进度条，不依赖固定坐标，无需校准）。

    def _reset_basketball_ball(self):
        if self.overlay:
            self.overlay.set_trail([])
            self.overlay.set_aim([])
        self._trail = deque(maxlen=36)
        for w in self.ball_windows:
            w.close()
        self.ball_windows = []
        fx, fy, fw, fh = self._basketball_field()
        r = self.config["appearance"]["radius"]
        self.basket = physics.Ball(x=fx + fw / 2, y=fy + fh - r - 4, r=r)
        win = self._make_window(ROLE_BASKET)
        win.set_center(self.basket.x, self.basket.y)
        self.ball_windows.append(win)
        self.sling = None

    # slingshot input (from PetWindow)
    def on_slingshot_start(self, win, gpos):
        self.sling = (gpos, 0.0, 0.0)

    def on_slingshot_drag(self, win, dx, dy):
        # aiming preview: full dashed line (no fade), disappears on launch
        if self.sling is None or self.basket is None:
            return
        self.sling = (self.sling[0], dx, dy)
        vx, vy = physics.slingshot_velocity(dx, dy, SLINGSHOT_K)
        pts = physics.trajectory_points(
            self.basket.x, self.basket.y, vx, vy, self.basket.r,
            self._basketball_field(), fraction=0.25)
        self.overlay.set_aim(pts)

    def on_slingshot_release(self, win, dx, dy, is_click):
        if self.sling is None or self.basket is None:
            return
        self.overlay.set_aim([])
        # first interaction while uncalibrated -> force hoop calibration
        # （不弹提示 toast：校准窗本身全屏带操作说明，避免“刚点完又弹
        # 校准提示”的观感 —— 旧版 3.5s 提示会在用户完成校准时仍挂在右下角）
        if not self.config["basketball"].get("hoop_calibrated"):
            self._calib_log("slingshot -> start_calibration (uncalibrated)")
            self.start_calibration()
            self.sling = None
            return
        if is_click:
            # 单击不再拍球：拍球改为空格键（见 _tick_space_slap）
            pass
        else:
            vx, vy = physics.slingshot_velocity(dx, dy, SLINGSHOT_K)
            self.basket.vx = vx
            self.basket.vy = vy
            self._play_launch_sound()
        self.sling = None

    def _play_launch_sound(self):
        self._play_sound(self.config["basketball"].get("launch_sound"))

    def _play_slap_sound(self):
        self._play_sound(self.config["basketball"].get("slap_sound"))

    def _play_sound(self, path):
        if not path:
            return
        # 相对路径（默认音效）→ 程序根目录下的绝对路径
        if not os.path.isabs(path):
            from .config import resolve_path
            path = resolve_path(path)
        if not os.path.exists(path):
            return
        if self.launch_player is None:
            self.launch_player = QMediaPlayer()
            self.launch_audio = QAudioOutput()
            self.launch_player.setAudioOutput(self.launch_audio)
        self.launch_player.stop()
        self.launch_player.setSource(QUrl.fromLocalFile(path))
        self.launch_player.play()

    # -------------------------------------------------------------- balloon
    def _enter_balloon(self):
        fx, fy, fw, fh = self.field
        r = self.config["appearance"]["radius"]
        count = min(10, int(self.config["balloon"].get("count", 10)))
        # 切换到气球模式时：注水默认 0%，气球漂浮于顶部
        self.config["balloon"]["water"] = 0
        save(self.config)
        water = 0
        target = physics.balloon_target_y(self.field, water)
        # 在顶部水平展开，彼此分开
        for i in range(count):
            win = self._make_window(ROLE_BALLOON)
            win.resize(int(r * 2), int(r * 2))
            win.set_water(water)
            cx = fx + fw / 2 + (i - (count - 1) / 2) * (r * 2 + 14)
            cy = fy + r + 6                  # 顶部漂浮
            win._bposy = float(cy)           # float center state (no int drift)
            win._bx = float(cx)
            win._btarget = target
            win._impulse_x = 0.0             # explosion shockwave impulse
            win._impulse_y = 0.0
            win.set_center(cx, cy)
            self.balloon_windows.append(win)
        # 爆炸特效画布（全屏、鼠标穿透）
        self.overlay = OverlayWindow(self.field)
        self.overlay.show()
        self._balloon_effects = []

    def on_balloon_dragged(self, win):
        # user is holding this balloon: pause ascent AND sync the float state
        # so the tick cannot snap the window back to its old position
        r = self.config["appearance"]["radius"]
        win._bx = float(win.x() + r)
        win._bposy = float(win.y() + r)
        win._btarget = None

    def on_balloon_release(self, win):
        # user released: balloon slowly rises to the water-limited height
        r = self.config["appearance"]["radius"]
        win._bposy = float(win.y() + r)
        win._bx = float(win.x() + r)
        win._btarget = physics.balloon_target_y(
            self.field, self.config["balloon"]["water"])

    def on_balloon_explode(self, win):
        """双击气球：爆炸——特效 + 音效 + 冲击波推开周围气球 + 积 2 分。"""
        if win not in self.balloon_windows:
            return
        cx, cy = win._bx, win._bposy
        r = self.config["appearance"]["radius"]
        self.balloon_windows.remove(win)
        win.close()

        # 爆炸特效：扩散圆环（叠加层绘制，随时间淡出）
        self._balloon_effects.append({
            "cx": cx, "cy": cy, "t": 0.0,
            "max_r": r * 7.0, "life": 0.8,
        })
        if self.overlay is not None:
            self.overlay.set_effects(list(self._balloon_effects))

        # 冲击波：显著增强，推开爆炸半径内的其他气球（强度可调）
        strength = float(self.config["balloon"].get("explode_strength", 150.0))
        balls = [(w._bx, w._bposy, r) for w in self.balloon_windows]
        impulses = physics.explosion_impulse(balls, (cx, cy), r * 6.0, strength)
        for win2, (ix, iy) in zip(self.balloon_windows, impulses):
            win2._impulse_x += ix
            win2._impulse_y += iy

        # 音效 + 独立计分（每爆一个 +2）
        self._play_sound(self.config["balloon"].get("explode_sound"))
        self._score_balloon(2)

        # 爆炸后在屏幕随机位置补充一个新气球
        self._spawn_one_balloon()

    def _spawn_one_balloon(self):
        fx, fy, fw, fh = self.field
        r = self.config["appearance"]["radius"]
        water = self.config["balloon"]["water"]
        win = self._make_window(ROLE_BALLOON)
        win.resize(int(r * 2), int(r * 2))
        win.set_water(water)
        win._bposy = float(fy + fh * random.uniform(0.2, 0.9))
        win._bx = float(fx + fw * random.uniform(0.1, 0.9))
        # 新气球实时响应当前注水百分比（无需鼠标操作）
        win._btarget = physics.balloon_target_y(self.field, water)
        win._impulse_x = 0.0
        win._impulse_y = 0.0
        win.set_center(win._bx, win._bposy)
        self.balloon_windows.append(win)

    def apply_water(self):
        if self.mode != MODE_BALLOON:
            return
        water = self.config["balloon"]["water"]
        target = physics.balloon_target_y(self.field, water)
        for win in self.balloon_windows:
            win.set_water(water)
            # more water -> lower target; the balloon responds in real time
            win._btarget = target
        save(self.config)

    # ----------------------------------------------------- appearance sync
    def apply_appearance(self):
        radius = self.config["appearance"]["radius"]
        skin = self.config["appearance"].get("skin_path")
        for w in self.ball_windows:
            w.apply_appearance(radius, skin)
        for win in self.balloon_windows:
            win.apply_appearance(radius, skin)
            win.resize(int(radius * 2), int(radius * 2))
        if self.idle_window:
            self.idle_window.apply_appearance(radius, skin)
            side = self._record_window_size()
            self.idle_window.resize(side, side)
        save(self.config)

    def apply_vinyl_ring(self):
        """黑胶外环半径（像素）变化时重设唱片窗口尺寸。"""
        if self.mode == MODE_IDLE and self.idle_window is not None:
            side = self._record_window_size()
            self.idle_window.resize(side, side)
            self.idle_window.update()
        save(self.config)

    def apply_sync_external(self):
        """同步外部模式开关：开启时停止本地音乐播放。"""
        if self._sync_on() and self.music_player is not None:
            self.music_player.pause()
            if self._record_playing:
                self._set_playing(False)

    def apply_pong_count(self):
        if self.mode == MODE_PONG:
            self.spawn_balls()
        save(self.config)

    def apply_balloon_count(self):
        if self.mode == MODE_BALLOON:
            self.switch_mode(MODE_BALLOON)   # recreate with the new count
        save(self.config)

    # -------------------------------------------------------------- scoring
    def _refresh_score_ui(self):
        """保存配置并刷新计分牌/设置面板（各模式计分共用）。"""
        save(self.config)
        self._update_score_label()
        if self.settings is not None:
            self.settings.refresh_scores()

    def _score_pong(self, delta):
        self.config["pong"]["score"] += delta
        self._refresh_score_ui()

    def _score_basket(self):
        self.config["basketball"]["score"] += HOOP_SCORE
        self._refresh_score_ui()
        self.tray.showMessage("篮球模式", f"进球！+{HOOP_SCORE} 分",
                              QSystemTrayIcon.Information, 1800)
        # 按设置决定是否在回收站生成 ball 文件（用户可关闭）
        if self.config["basketball"].get("drop_ball_file", True):
            self._drop_ball_file_into_recycle_bin()

    # ------------------------------------------------- recycle-bin file
    def _drop_ball_file_into_recycle_bin(self):
        """每次进球后，往回收站投放一个名为 ball 的无扩展名空文件。

        通过 SHFileOperation FO_DELETE + FOF_ALLOWUNDO 把临时文件删除到回收站。
        """
        import ctypes
        from ctypes import wintypes
        try:
            tmp_dir = os.path.join(
                os.environ.get("TEMP") or os.path.expanduser("~"), "DesktopPet_ball")
            os.makedirs(tmp_dir, exist_ok=True)
            ball_path = os.path.join(tmp_dir, "ball")
            with open(ball_path, "wb"):
                pass

            class SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040
            FOF_SILENT = 0x0004
            FOF_NOCONFIRMATION = 0x0010
            src = ball_path + "\0\0"
            op = SHFILEOPSTRUCTW(hwnd=None, wFunc=FO_DELETE,
                                 pFrom=src, pTo=None,
                                 fFlags=FOF_ALLOWUNDO | FOF_SILENT | FOF_NOCONFIRMATION)
            shell32 = ctypes.windll.shell32
            shell32.SHFileOperationW(ctypes.byref(op))
        except Exception:
            pass   # 投放失败不影响游戏

    def reset_pong_score(self):
        self.config["pong"]["score"] = 0
        self._refresh_score_ui()

    def reset_basketball_score(self):
        self.config["basketball"]["score"] = 0
        self._refresh_score_ui()

    def _score_balloon(self, delta):
        self.config["balloon"]["score"] = \
            self.config["balloon"].get("score", 0) + delta
        self._refresh_score_ui()

    def reset_balloon_score(self):
        self.config["balloon"]["score"] = 0
        self._refresh_score_ui()

    # ------------------------------------------------------------- menus
    def build_context_menu(self, menu, win):
        self._add_menu_mode_actions(menu)
        self._add_menu_tail(menu)

    # ---------------------------------------------------------- hide/show
    def toggle_hidden(self):
        self.hidden = not self.hidden
        visible = not self.hidden
        for w in self.ball_windows:
            w.setVisible(visible)
        if self.platform_top:
            self.platform_top.setVisible(visible)
        if self.platform_bottom:
            self.platform_bottom.setVisible(visible)
        if self.overlay:
            self.overlay.setVisible(visible)
        if self.score_label:
            self.score_label.setVisible(visible and self.mode in
                                        (MODE_PONG, MODE_BASKETBALL, MODE_BALLOON))
        for win in self.balloon_windows:
            win.setVisible(visible)
        if self.idle_window:
            self.idle_window.setVisible(visible)
        if self.settings is not None:
            self.settings.close()

    def open_settings(self):
        if self.settings is None:
            self.settings = SettingsDialog(self)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    # -------------------------------------------------------------- tick
    def _tick(self):
        now_ms = int(time.monotonic() * 1000)
        dt = TICK_MS / 1000.0
        if self.mode == MODE_PONG:
            self._tick_pong(dt)
        elif self.mode == MODE_BASKETBALL:
            self._tick_basketball(dt)
            self._tick_space_slap()
        elif self.mode == MODE_BALLOON:
            self._tick_balloon(dt)
        elif self.mode == MODE_IDLE:
            self._tick_record(dt)

    def _tick_space_slap(self):
        """空格键拍球：边沿触发，长按只触发一次。"""
        down = _key_down(VK_SPACE)
        if down and not self._space_down_prev:
            if self.basket is not None and \
                    self.config["basketball"].get("hoop_calibrated"):
                physics.slap_down(self.basket, SLAP_IMPULSE)
                self._play_slap_sound()
        self._space_down_prev = down

    def _tick_record(self, dt):
        """唱片模式：唱片针始终平滑动画；仅实际播放时旋转球体。

        同步外部模式：动画由 SMTC 轮询的外部播放状态驱动（无外部会话时
        沿用内部状态）；本地模式：以本地播放器实际播放状态为准。
        """
        if self.idle_window is None:
            return
        # 唱片针平滑过渡（播放→搭上，停止→移开）
        self.idle_window.animate_tonearm(dt)
        if self.record_panel is not None and self.record_panel.isVisible():
            self.record_panel.sync_progress()
        if self._sync_on():
            self._poll_smtc()
            playing = self._record_playing
        else:
            playing = self._record_playing and self.music_player is not None and \
                self.music_player.playbackState() == QMediaPlayer.PlayingState
        if not playing:
            return
        cfg = self.config.get("record", {})
        speed = float(cfg.get("rotate_speed", 90))
        if cfg.get("rotate_dir", "cw") == "ccw":
            speed = -speed
        self._record_angle = (self._record_angle + speed * dt) % 360.0
        self.idle_window.set_rotation(self._record_angle)

    def _poll_smtc(self):
        """每 500ms 轮询一次外部播放器（SMTC）：同步进度与播放状态；
        每 ~2.5s 刷新一次当前曲目/视频标题（显示在进度条下方）。"""
        now_ms = int(time.monotonic() * 1000)
        if now_ms - getattr(self, "_smtc_last_poll", 0) < 500:
            return
        self._smtc_last_poll = now_ms
        try:
            from . import smtc
            snap = smtc.snapshot()
        except Exception:
            snap = None
        if snap is None:
            return
        playing, pos, dur = snap
        if playing != self._record_playing:
            self._record_playing = playing
            if self.idle_window is not None:
                self.idle_window.set_tonearm_engaged(playing)
        if self.record_panel is not None:
            self.record_panel.sync_external_progress(playing, pos, dur)
            n = getattr(self, "_smtc_poll_count", 0) + 1
            self._smtc_poll_count = n
            if n % 5 == 0:
                import threading
                threading.Thread(target=self._fetch_external_title,
                                 daemon=True).start()

    def _apply_external_title(self, title):
        if self.record_panel is not None:
            self.record_panel.set_external_title(title)

    def _fetch_external_title(self):
        """后台线程获取外部曲目/视频标题（进度条下方显示）。"""
        try:
            from . import smtc
            t = smtc.title()
        except Exception:
            t = ""
        if t:
            # 跨线程更新 Qt 控件：经信号桥回到主线程（QTimer.singleShot
            # 在工作线程创建的定时器不会触发）
            self._title_bridge.title_ready.emit(t)

    def _tick_pong(self, dt):
        if self.pong is None or self.platform_top is None or self.platform_bottom is None:
            return
        fx, fy, fw, fh = self.field

        # user paddle: Left/Right held state via GetAsyncKeyState
        self.keys["left"] = _key_down(VK_LEFT)
        self.keys["right"] = _key_down(VK_RIGHT)
        speed = 560.0
        bx, by, bw, bh = self.platform_bottom.get_rect()
        if self.keys["left"]:
            bx = max(fx, bx - speed * dt)
        if self.keys["right"]:
            bx = min(fx + fw - bw, bx + speed * dt)
        self.platform_bottom.set_platform(bx, by)

        # AI top platform follows the ball closest to the top (most urgent),
        # with the configured difficulty (speed + predictive aiming)
        if self.pong.balls:
            ball = min(self.pong.balls, key=lambda b: b.y)
            diff = DIFFICULTY.get(self.config["pong"].get("difficulty", "bean"),
                                  DIFFICULTY["bean"])
            tx, ty, tw, th = self.platform_top.get_rect()
            tx = physics.pong_ai_step(
                (tx, ty, tw, th), ball, dt,
                speed=diff["speed"], predictive=diff["predictive"],
                field=self.field)[0]
            self.platform_top.set_platform(tx, ty)

        # sync platform rects into the physics state BEFORE stepping
        self.pong.top_platform = self.platform_top.get_rect()
        self.pong.bottom_platform = self.platform_bottom.get_rect()

        # physics
        events = physics.pong_step(self.pong, dt, self.field)
        lost_idx = []
        for kind, idx in events:
            if kind == "lost_top":
                self._score_pong(+1)
            elif kind == "lost_bottom":
                self._score_pong(-1)
            lost_idx.append(idx)
        # remove ball windows (descending so indices stay valid)
        for idx in sorted(lost_idx, reverse=True):
            if 0 <= idx < len(self.ball_windows):
                self.ball_windows[idx].close()
                self.ball_windows.pop(idx)

        # 弹珠之间的物理碰撞（弹性反弹）
        if len(self.pong.balls) > 1:
            physics.pong_ball_collision(self.pong.balls)

        # 自动补充：场上为空时，按设置间隔生成一个，直到补足设定数量
        interval = max(0.25, float(self.config["pong"].get("spawn_interval", 1.0)))
        if self.pong and not self.pong.balls and self._pong_pending == 0:
            self._pong_pending = min(10, int(self.config["pong"]["ball_count"]))
            self._pong_next_spawn = time.monotonic() + interval
        if self._pong_pending > 0 and time.monotonic() >= self._pong_next_spawn:
            self._spawn_one_pong_ball()
            self._pong_pending -= 1
            self._pong_next_spawn = time.monotonic() + interval

        # sync windows to physics balls
        for i, b in enumerate(self.pong.balls):
            if i < len(self.ball_windows):
                self.ball_windows[i].set_center(b.x, b.y)

    def _tick_basketball(self, dt):
        if self.basket is None:
            return
        if len(self.ball_windows) == 0:
            return
        physics.projectile_step(self.basket, dt, self._basketball_field())
        self.ball_windows[0].set_center(self.basket.x, self.basket.y)

        # motion trail: only while the ball is actually moving; a still ball
        # must NOT accumulate identical dots at its center (visible yellow dot)
        speed2 = self.basket.vx * self.basket.vx + self.basket.vy * self.basket.vy
        if speed2 > 400.0:                       # ~20 px/s
            self._trail.append((self.basket.x, self.basket.y))
            self.overlay.set_trail(list(self._trail))
        elif self._trail:
            self._trail.clear()
            self.overlay.set_trail([])

        # hoop scoring: ball center near the real Recycle Bin icon
        if self.hoop_enabled and self.hoop_pos is not None:
            now = int(time.monotonic() * 1000)
            if now >= self.hoop_cooldown_until:
                hx, hy = self.hoop_pos
                hoop_r = HOOP_RADIUS
                d = math.hypot(self.basket.x - hx, self.basket.y - hy)
                if d <= hoop_r + self.basket.r * 0.4:
                    self._score_basket()
                    self.hoop_cooldown_until = now + HOOP_COOLDOWN_MS
                    self._reset_basketball_ball()   # auto new ball

    def _tick_balloon(self, dt):
        if not self.balloon_windows and not self._balloon_effects:
            return
        r = self.config["appearance"]["radius"]
        fx, fy, fw, fh = self.field

        # 1) uniform-speed vertical motion toward each balloon's target
        for win in self.balloon_windows:
            if getattr(win, "_btarget", None) is None:
                continue
            win._bposy = physics.balloon_step(win._bposy, win._btarget, dt)

        # 2) explosion shockwave impulses (decay over time)
        for win in self.balloon_windows:
            win._bx += win._impulse_x * dt
            win._bposy += win._impulse_y * dt
            win._impulse_x *= 0.90
            win._impulse_y *= 0.90

        # 3) very weak mutual attraction; the balloon the user is dragging is
        #    exempt from attraction so it can be pulled away freely
        fx2, fy2, fw2, fh2 = self.field
        balls = [(w._bx, w._bposy, r) for w in self.balloon_windows]
        offsets = physics.balloon_attraction(balls)
        dragging = [getattr(w, "_dragging", False) for w in self.balloon_windows]
        for win, (ox, oy), is_drag in zip(self.balloon_windows, offsets, dragging):
            if is_drag:
                continue
            win._bx += ox
            win._bposy += oy

        # 4) hard collision volume: overlapping balloons push apart
        coll = physics.balloon_collision(balls)
        for win, (ox, oy) in zip(self.balloon_windows, coll):
            win._bx += ox
            win._bposy += oy

        # 5) keep inside the field
        for win in self.balloon_windows:
            win._bx = max(fx + r, min(fx + fw - r, win._bx))
            win._bposy = max(fy + r, min(fy + fh - r, win._bposy))

        # 6) place windows from the float state (no integer drift)
        for win in self.balloon_windows:
            win.set_center(win._bx, win._bposy)

        # 7) explosion visual effects (expanding fading rings)
        alive = []
        for ef in self._balloon_effects:
            ef["t"] += dt
            if ef["t"] < ef["life"]:
                alive.append(ef)
        self._balloon_effects = alive
        if self.overlay is not None:
            self.overlay.set_effects(list(self._balloon_effects))

    # ------------------------------------------------------------ selftest
    def selftest_scores(self):
        """Exercise the app-level scoring paths. Returns list of (name, ok)."""
        import time
        results = []

        # pong: a ball passing the top edge must award +1 (auto-respawn may
        # add further events afterwards, so assert the first loss happened)
        self.switch_mode(MODE_PONG)
        time.sleep(0.3)
        start = self.config["pong"]["score"]
        if self.pong and self.pong.balls:
            r = self.config["appearance"]["radius"]
            fx, fy, fw, fh = self.field
            # place the ball far left so the centered platforms can't catch it
            self.pong.balls[0].x = fx + r + 8
            self.pong.balls[0].y = fy + 110
            self.pong.balls[0].vy = -500
            self.pong.balls[0].vx = 0
            for _ in range(20):
                self._tick_pong(TICK_MS / 1000.0)
                if self.config["pong"]["score"] > start:
                    break
        results.append(("pong top-loss awards +1",
                        self.config["pong"]["score"] > start))
        self.respawn_balls()

        # basketball: ball on the real Recycle Bin icon awards +3
        # (selftest calibrates a hoop directly — the real flow prompts the
        # user to click their Recycle Bin on first interaction)
        self.config["basketball"]["hoop_calibrated"] = True
        self.config["basketball"]["hoop_pos"] = [self.field[0] + 300, self.field[1] + 300]
        save(self.config)
        self.switch_mode(MODE_BASKETBALL)
        time.sleep(0.3)
        start = self.config["basketball"]["score"]
        if self.basket and self.hoop_pos and self.hoop_enabled:
            hx, hy = self.hoop_pos
            self.basket.x = hx
            self.basket.y = hy
            self.basket.vx = 0.0
            self.basket.vy = 0.0
            self.hoop_cooldown_until = 0
            for _ in range(6):
                self._tick_basketball(TICK_MS / 1000.0)
        results.append(("basket hoop awards +3",
                        self.config["basketball"]["score"] == start + 3))
        return results


class _TitleBridge(QObject):
    """工作线程 → 主线程 的信号桥（标题显示）。"""
    title_ready = Signal(str)


class _CalibrationWindow(QWidget):
    """Full-screen translucent click catcher for hoop calibration."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "background: rgba(20,20,30,180); color: white;"
            "font: bold 18px 'Microsoft YaHei';")

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 30, 180))
        p.setPen(QColor(255, 255, 255, 235))
        f = QFont("Microsoft YaHei", 18, QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter,
                   "请点击桌面上的「回收站」图标\n（左键点击即校准，右键取消）")
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.app._close_calibration()
            self.app._restore_gameplay_windows()
        else:
            self.app._on_calibration_click(e.globalPosition())
        e.accept()
