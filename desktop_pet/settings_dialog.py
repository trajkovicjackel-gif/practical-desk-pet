# -*- coding: utf-8 -*-
"""Settings dialog: per-mode tabs with independent controls & scores."""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSlider, QLabel, QPushButton, QSpinBox, QFileDialog, QGroupBox,
    QCheckBox, QComboBox, QListWidget,
)


def _make_slider(lo, hi, step, value, callback):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setPageStep(step)
    s.setValue(value)
    s.valueChanged.connect(callback)
    return s


class SettingsDialog(QDialog):
    def __init__(self, app_controller, parent=None):
        super().__init__(parent)
        self.ctrl = app_controller
        self.cfg = app_controller.config
        self.setWindowTitle("桌宠设置")
        self.setMinimumWidth(420)
        self.setModal(False)

        tabs = QTabWidget()
        tabs.addTab(self._tab_appearance(), "外观")
        tabs.addTab(self._tab_pong(), "弹珠模式")
        tabs.addTab(self._tab_basketball(), "篮球模式")
        tabs.addTab(self._tab_balloon(), "气球模式")
        tabs.addTab(self._tab_record(), "唱片模式")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)

    # ------------------------------------------------------------ appearance
    def _tab_appearance(self):
        box = QGroupBox("外观与基础设置")
        form = QFormLayout(box)

        self.radius_value = QLabel()
        self.radius_slider = _make_slider(
            50, 200, 10, self.cfg["appearance"]["radius"],
            self._on_radius)
        self._update_radius_label()
        form.addRow("圆形半径", self.radius_slider)
        form.addRow("当前半径", self.radius_value)

        self._skin_preview = QLabel("（未使用自定义皮肤）")
        self._skin_preview.setFixedHeight(72)
        form.addRow("皮肤预览", self._skin_preview)
        self._refresh_skin_preview()   # 已设置皮肤时不再显示“未使用”

        skin_row = QHBoxLayout()
        upload = QPushButton("上传皮肤图像")
        upload.clicked.connect(self._on_upload_skin)
        clear = QPushButton("恢复默认")
        clear.clicked.connect(self._on_clear_skin)
        skin_row.addWidget(upload)
        skin_row.addWidget(clear)
        form.addRow(skin_row)
        return box

    def _set_both(self, section, key, value):
        """同时写入对话框缓存与真实配置并保存（各设置项共用）。"""
        self.cfg[section][key] = value
        self.ctrl.config[section][key] = value
        from .config import save
        save(self.ctrl.config)

    def _update_record_speed_label(self):
        self.record_speed_value.setText(
            f"{int(self.cfg.get('record', {}).get('rotate_speed', 90))} 度/秒")

    def _on_record_speed(self, v):
        self._set_both("record", "rotate_speed", int(v))
        self._update_record_speed_label()

    def _on_record_dir(self, idx):
        self._set_both("record", "rotate_dir", self.record_dir.itemData(idx))

    # -------------------------------------------------------------- record
    def _tab_record(self):
        box = QGroupBox("唱片模式")
        form = QFormLayout(box)

        # 歌单管理
        self.playlist_list = QListWidget()
        self.playlist_list.setFixedHeight(90)
        self._refresh_playlist()
        form.addRow("歌单", self.playlist_list)

        pl_row = QHBoxLayout()
        add_song = QPushButton("添加歌曲")
        add_song.clicked.connect(self._on_add_songs)
        import_folder = QPushButton("导入文件夹")
        import_folder.clicked.connect(self._on_import_folder)
        remove_song = QPushButton("移除选中")
        remove_song.clicked.connect(self._on_remove_song)
        clear_songs = QPushButton("清空")
        clear_songs.clicked.connect(self._on_clear_songs)
        pl_row.addWidget(add_song)
        pl_row.addWidget(import_folder)
        pl_row.addWidget(remove_song)
        pl_row.addWidget(clear_songs)
        form.addRow(pl_row)

        self.auto_next = QCheckBox("一首播放完毕自动播放下一首")
        self.auto_next.setChecked(bool(self.cfg.get("record", {}).get("auto_next", True)))
        self.auto_next.toggled.connect(self._on_auto_next)
        form.addRow(self.auto_next)

        self.play_mode = QComboBox()
        for key, label in (("single_loop", "单曲循环"), ("list_loop", "列表循环"),
                           ("sequential", "顺序播放"), ("shuffle", "随机播放")):
            self.play_mode.addItem(label, key)
        midx = self.play_mode.findData(self.cfg.get("record", {}).get("playback_mode", "list_loop"))
        self.play_mode.setCurrentIndex(max(0, midx))
        self.play_mode.currentIndexChanged.connect(self._on_play_mode)
        form.addRow("播放模式", self.play_mode)

        self.record_dir = QComboBox()
        self.record_dir.addItem("顺时针", "cw")
        self.record_dir.addItem("逆时针", "ccw")
        ridx = self.record_dir.findData(self.cfg.get("record", {}).get("rotate_dir", "cw"))
        self.record_dir.setCurrentIndex(max(0, ridx))
        self.record_dir.currentIndexChanged.connect(self._on_record_dir)
        form.addRow("旋转方向", self.record_dir)

        self.record_speed_value = QLabel()
        self.record_speed_slider = _make_slider(
            15, 360, 15, self.cfg.get("record", {}).get("rotate_speed", 90),
            self._on_record_speed)
        self._update_record_speed_label()
        form.addRow("旋转速度", self.record_speed_slider)
        form.addRow("当前速度", self.record_speed_value)

        self.vinyl_value = QLabel()
        self.vinyl_slider = _make_slider(
            50, 350, 5, int(self.cfg.get("record", {}).get("vinyl_ring_r", 120.0)),
            self._on_vinyl_ring)
        self._update_vinyl_label()
        form.addRow("黑胶外圈半径（像素）", self.vinyl_slider)
        form.addRow("当前半径", self.vinyl_value)

        self.sync_ext = QCheckBox("同步控制外部音乐软件（发送系统媒体键）")
        self.sync_ext.setChecked(bool(self.cfg.get("record", {}).get("sync_external", True)))
        self.sync_ext.toggled.connect(self._on_sync_external)
        form.addRow(self.sync_ext)

        ext_row = QHBoxLayout()
        self.ext_session = QComboBox()
        self._refresh_ext_sessions()
        self.ext_session.currentIndexChanged.connect(self._on_ext_session)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setToolTip("重新扫描当前打开的播放器（无需重启应用）")
        refresh_btn.clicked.connect(self._refresh_ext_sessions)
        ext_row.addWidget(self.ext_session, 1)
        ext_row.addWidget(refresh_btn)
        form.addRow("外部播放器", ext_row)

        return box

    def _update_vinyl_label(self):
        self.vinyl_value.setText(
            f"{int(self.cfg.get('record', {}).get('vinyl_ring_r', 120.0))} 像素")

    def _on_vinyl_ring(self, v):
        v = round(v / 5) * 5
        self._set_both("record", "vinyl_ring_r", float(v))
        self._update_vinyl_label()
        self.ctrl.apply_vinyl_ring()

    def _on_sync_external(self, checked):
        self._set_both("record", "sync_external", bool(checked))
        self.ctrl.apply_sync_external()

    def _refresh_ext_sessions(self):
        """刷新外部播放器下拉列表（自动 + 当前所有 SMTC 会话）。"""
        try:
            from . import smtc
            sessions = smtc.list_sessions()
            cur = smtc.get_selected()
        except Exception:
            sessions, cur = [], "auto"
        self.ext_session.blockSignals(True)
        self.ext_session.clear()
        self.ext_session.addItem("自动选择（播放中优先，其次最近更新）", "auto")
        for s in sessions:
            label = os.path.basename(s.get("app_id") or "") or "未知应用"
            if s.get("playing"):
                label = "▶ " + label
            if s.get("title"):
                label += f" · {s['title'][:20]}"
            self.ext_session.addItem(label, s.get("app_id"))
        idx = self.ext_session.findData(cur)
        self.ext_session.setCurrentIndex(max(0, idx))
        self.ext_session.blockSignals(False)

    def _on_ext_session(self, idx):
        val = self.ext_session.itemData(idx)
        if val is None:
            return
        self._set_both("record", "external_session", val)
        try:
            from . import smtc
            smtc.set_selected(val)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "ext_session"):
            self._refresh_ext_sessions()
        if hasattr(self, "hoop_info"):
            self.refresh_hoop_label()   # 校准可能发生在对话框创建之后
        if hasattr(self, "_skin_preview"):
            self._refresh_skin_preview()   # 皮肤可能在其他流程中设置

    def _refresh_playlist(self):
        self.playlist_list.clear()
        for path in (self.cfg.get("record", {}).get("playlist") or []):
            self.playlist_list.addItem(os.path.basename(path))

    AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma")

    @staticmethod
    def scan_audio_files(folder):
        """递归扫描文件夹内的音频文件（排序稳定）。"""
        found = []
        for root, _dirs, files in os.walk(folder):
            for f in sorted(files):
                if f.lower().endswith(SettingsDialog.AUDIO_EXTS):
                    found.append(os.path.join(root, f))
        return found

    def _on_import_folder(self):
        """一键导入文件夹：递归添加其中全部音频到歌单。"""
        folder = QFileDialog.getExistingDirectory(
            self, "选择歌曲文件夹（递归导入全部音频）")
        if not folder:
            return
        found = self.scan_audio_files(folder)
        if not found:
            return
        playlist = list(self.cfg.get("record", {}).get("playlist") or [])
        added = 0
        for p in found:
            if p not in playlist:
                playlist.append(p)
                added += 1
        if added == 0:
            return
        self.cfg["record"]["playlist"] = playlist
        self.ctrl.config["record"]["playlist"] = playlist
        from .config import save
        save(self.ctrl.config)
        self._refresh_playlist()

    def _on_add_songs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择歌曲（可多选）", "", "Audio (*.mp3 *.wav *.ogg *.flac)")
        if paths:
            playlist = list(self.cfg.get("record", {}).get("playlist") or [])
            for p in paths:
                if p not in playlist:
                    playlist.append(p)
            self.cfg["record"]["playlist"] = playlist
            self.ctrl.config["record"]["playlist"] = playlist
            from .config import save
            save(self.ctrl.config)
            self._refresh_playlist()

    def _on_remove_song(self):
        row = self.playlist_list.currentRow()
        playlist = list(self.cfg.get("record", {}).get("playlist") or [])
        if 0 <= row < len(playlist):
            playlist.pop(row)
            self.cfg["record"]["playlist"] = playlist
            self.ctrl.config["record"]["playlist"] = playlist
            from .config import save
            save(self.ctrl.config)
            self._refresh_playlist()

    def _on_clear_songs(self):
        self.cfg["record"]["playlist"] = []
        self.ctrl.config["record"]["playlist"] = []
        from .config import save
        save(self.ctrl.config)
        self._refresh_playlist()

    def _on_auto_next(self, checked):
        self._set_both("record", "auto_next", bool(checked))

    def _on_play_mode(self, idx):
        self._set_both("record", "playback_mode", self.play_mode.itemData(idx))

    def _update_radius_label(self):
        v = self.cfg["appearance"]["radius"]
        self.radius_value.setText(f"{v} 像素")

    def _on_radius(self, v):
        v = round(v / 10) * 10
        self.cfg["appearance"]["radius"] = v
        self._update_radius_label()
        self.ctrl.apply_appearance()

    def _on_upload_skin(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择皮肤图像", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if not path:
            return
        from .crop_dialog import CropDialog
        dlg = CropDialog(path, self)
        if dlg.exec():
            self.cfg["appearance"]["skin_path"] = dlg.cropped_path
            self.ctrl.apply_appearance()
            self._refresh_skin_preview()

    def _on_clear_skin(self):
        self.cfg["appearance"]["skin_path"] = None
        self.ctrl.apply_appearance()
        self._refresh_skin_preview()

    def _refresh_skin_preview(self):
        path = self.cfg["appearance"].get("skin_path")
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._skin_preview.setPixmap(
                    pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self._skin_preview.setText("（未使用自定义皮肤）")

    # ---------------------------------------------------------------- pong
    def _tab_pong(self):
        box = QGroupBox("弹珠模式")
        form = QFormLayout(box)

        self.pong_count = QSpinBox()
        self.pong_count.setRange(1, 10)
        self.pong_count.setValue(self.cfg["pong"]["ball_count"])
        self.pong_count.valueChanged.connect(self._on_pong_count)
        form.addRow("同时存在的弹珠数", self.pong_count)

        self.pong_speed_value = QLabel()
        self.pong_speed_slider = _make_slider(
            100, 1000, 20, self.cfg["pong"].get("ball_speed", 340),
            self._on_pong_speed)
        self._update_pong_speed_label()
        form.addRow("弹珠飞行速度", self.pong_speed_slider)
        form.addRow("当前速度", self.pong_speed_value)

        from PySide6.QtWidgets import QComboBox
        self.pong_diff = QComboBox()
        for key, label in (("bean", "豆包"), ("simple", "简单"),
                           ("normal", "正常"), ("hell", "地狱"),
                           ("king", "王者")):
            self.pong_diff.addItem(label, key)
        idx = self.pong_diff.findData(self.cfg["pong"].get("difficulty", "bean"))
        self.pong_diff.setCurrentIndex(max(0, idx))
        self.pong_diff.currentIndexChanged.connect(self._on_pong_diff)
        form.addRow("AI 平台难度", self.pong_diff)

        self.spawn_value = QLabel()
        self.spawn_slider = _make_slider(
            25, 500, 25, int(float(self.cfg["pong"].get("spawn_interval", 1.0)) * 100),
            self._on_spawn_interval)
        self._update_spawn_label()
        form.addRow("出球间隔", self.spawn_slider)
        form.addRow("当前间隔", self.spawn_value)

        self.pong_score = QLabel()
        self._refresh_pong_score()
        form.addRow("本模式得分", self.pong_score)

        reset = QPushButton("重置弹珠得分")
        reset.clicked.connect(self.ctrl.reset_pong_score)
        form.addRow(reset)
        return box

    def _update_spawn_label(self):
        v = float(self.cfg["pong"].get("spawn_interval", 1.0))
        self.spawn_value.setText(f"{v:.2f} 秒")

    def _on_spawn_interval(self, v):
        v = round(v / 25) * 25
        sec = v / 100.0
        self.cfg["pong"]["spawn_interval"] = sec
        self._update_spawn_label()
        from .config import save
        save(self.ctrl.config)

    def _update_pong_speed_label(self):
        self.pong_speed_value.setText(
            f"{int(self.cfg['pong'].get('ball_speed', 340))} px/s")

    def _on_pong_speed(self, v):
        v = round(v / 20) * 20
        self._set_both("pong", "ball_speed", v)
        self._update_pong_speed_label()
        if self.ctrl.mode == "pong":
            self.ctrl.spawn_balls()

    def _on_pong_diff(self, idx):
        self._set_both("pong", "difficulty", self.pong_diff.itemData(idx))

    def _on_pong_count(self, v):
        self.cfg["pong"]["ball_count"] = v
        self.ctrl.apply_pong_count()

    def _refresh_pong_score(self):
        self.pong_score.setText(str(self.cfg["pong"]["score"]))

    def refresh_scores(self):
        self._refresh_pong_score()
        if hasattr(self, "basketball_score"):
            self.basketball_score.setText(str(self.cfg["basketball"]["score"]))
        if hasattr(self, "balloon_score"):
            self.balloon_score.setText(str(self.cfg["balloon"].get("score", 0)))

    # ----------------------------------------------------------- basketball
    def _tab_basketball(self):
        box = QGroupBox("篮球模式")
        form = QFormLayout(box)

        self.basketball_score = QLabel()
        self.basketball_score.setText(str(self.cfg["basketball"]["score"]))
        form.addRow("本模式得分", self.basketball_score)

        reset = QPushButton("重置篮球得分")
        reset.clicked.connect(self.ctrl.reset_basketball_score)
        form.addRow(reset)

        sound_row = QHBoxLayout()
        self.sound_path_label = QLabel(self.cfg["basketball"].get("launch_sound") or "（默认音效）")
        self.sound_path_label.setWordWrap(True)
        pick = QPushButton("选择发射音效")
        pick.clicked.connect(self._on_pick_sound)
        reset_sound = QPushButton("恢复默认")
        reset_sound.clicked.connect(self._on_reset_sound)
        sound_row.addWidget(pick)
        sound_row.addWidget(reset_sound)
        form.addRow("发射音效", self.sound_path_label)
        form.addRow(sound_row)

        slap_row = QHBoxLayout()
        self.slap_path_label = QLabel(self.cfg["basketball"].get("slap_sound") or "（默认音效）")
        self.slap_path_label.setWordWrap(True)
        pick_slap = QPushButton("选择拍球音效")
        pick_slap.clicked.connect(self._on_pick_slap_sound)
        reset_slap = QPushButton("恢复默认")
        reset_slap.clicked.connect(self._on_reset_slap_sound)
        slap_row.addWidget(pick_slap)
        slap_row.addWidget(reset_slap)
        form.addRow("拍球音效", self.slap_path_label)
        form.addRow(slap_row)

        calib_row = QHBoxLayout()
        calib = QPushButton("校准回收站位置")
        calib.clicked.connect(self._on_calibrate_hoop)
        self.hoop_info = QLabel(str(self.cfg["basketball"].get("hoop_pos")))
        calib_row.addWidget(calib)
        calib_row.addWidget(self.hoop_info)
        form.addRow("回收站篮筐", calib_row)

        reset_calib = QPushButton("重置校准（清除已保存位置）")
        reset_calib.clicked.connect(self.ctrl._reset_hoop_calibration)
        form.addRow(reset_calib)

        self.drop_ball_check = QCheckBox("进球时在回收站中生成 ball 文件")
        self.drop_ball_check.setChecked(
            bool(self.cfg["basketball"].get("drop_ball_file", True)))
        self.drop_ball_check.toggled.connect(self._on_drop_ball_file)
        form.addRow(self.drop_ball_check)
        return box

    def _on_drop_ball_file(self, checked):
        self._set_both("basketball", "drop_ball_file", bool(checked))

    def refresh_hoop_label(self):
        if hasattr(self, "hoop_info"):
            self.hoop_info.setText(str(self.cfg["basketball"].get("hoop_pos")))

    def _on_calibrate_hoop(self):
        self.close()
        self.ctrl.start_calibration()

    def _on_pick_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择发射音效", "", "Audio (*.mp3 *.wav *.ogg *.flac)")
        if path:
            self.cfg["basketball"]["launch_sound"] = path
            self.ctrl.config["basketball"]["launch_sound"] = path
            self.sound_path_label.setText(path)

    def _on_reset_sound(self):
        from .config import DEFAULTS
        self.cfg["basketball"]["launch_sound"] = DEFAULTS["basketball"]["launch_sound"]
        self.ctrl.config["basketball"]["launch_sound"] = DEFAULTS["basketball"]["launch_sound"]
        self.sound_path_label.setText("（默认音效）")

    def _on_pick_slap_sound(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择拍球音效", "", "Audio (*.mp3 *.wav *.ogg *.flac)")
        if path:
            self.cfg["basketball"]["slap_sound"] = path
            self.ctrl.config["basketball"]["slap_sound"] = path
            self.slap_path_label.setText(path)

    def _on_reset_slap_sound(self):
        from .config import DEFAULTS
        self.cfg["basketball"]["slap_sound"] = DEFAULTS["basketball"]["slap_sound"]
        self.ctrl.config["basketball"]["slap_sound"] = DEFAULTS["basketball"]["slap_sound"]
        self.slap_path_label.setText("（默认音效）")

    # -------------------------------------------------------------- balloon
    def _tab_balloon(self):
        box = QGroupBox("气球模式")
        form = QFormLayout(box)

        self.balloon_count = QSpinBox()
        self.balloon_count.setRange(1, 10)
        self.balloon_count.setValue(self.cfg["balloon"].get("count", 10))
        self.balloon_count.valueChanged.connect(self._on_balloon_count)
        form.addRow("同时存在的气球数", self.balloon_count)

        self.water_value = QLabel()
        self.water_slider = _make_slider(
            0, 100, 1, self.cfg["balloon"]["water"], self._on_water)
        self._update_water_label()
        form.addRow("注水百分比", self.water_slider)
        form.addRow("当前注水", self.water_value)

        self.balloon_score = QLabel(str(self.cfg["balloon"].get("score", 0)))
        form.addRow("本模式得分（每爆一个 +2）", self.balloon_score)
        reset = QPushButton("重置气球得分")
        reset.clicked.connect(self.ctrl.reset_balloon_score)
        form.addRow(reset)

        self.explode_value = QLabel()
        self.explode_slider = _make_slider(
            0, 1000, 10, int(self.cfg["balloon"].get("explode_strength", 250.0)),
            self._on_explode_strength)
        self._update_explode_label()
        form.addRow("爆炸冲击波强度", self.explode_slider)
        form.addRow("当前强度", self.explode_value)

        # 四态外观图像：按注水比例显示
        self.balloon_image_labels = []
        for i, pct in enumerate((0, 25, 50, 100)):
            row = QHBoxLayout()
            label = QLabel("（默认）")
            label.setWordWrap(True)
            self.balloon_image_labels.append(label)
            btn = QPushButton(f"注水{pct}%")
            btn.clicked.connect(lambda _c, idx=i: self._on_pick_balloon_image(idx))
            clear_btn = QPushButton("清除")
            clear_btn.clicked.connect(lambda _c, idx=i: self._on_clear_balloon_image(idx))
            row.addWidget(btn)
            row.addWidget(clear_btn)
            row.addWidget(label)
            form.addRow(f"外观 注水{pct}%", row)
        self._refresh_balloon_images()

        tip = QLabel("水越多球越低，球越低球越重，球越重球越大，"
                     "球越大水越少，所以水越多水越少")
        tip.setWordWrap(True)
        form.addRow(tip)
        return box

    def _on_balloon_count(self, v):
        self.cfg["balloon"]["count"] = v
        self.ctrl.apply_balloon_count()

    def _update_explode_label(self):
        self.explode_value.setText(
            f"{int(self.cfg['balloon'].get('explode_strength', 150.0))}")

    def _on_explode_strength(self, v):
        self.cfg["balloon"]["explode_strength"] = int(v)
        self._update_explode_label()
        from .config import save
        save(self.ctrl.config)

    def _refresh_balloon_images(self):
        images = self.cfg.get("balloon", {}).get("images") or [None] * 4
        for i, label in enumerate(self.balloon_image_labels):
            p = images[i] if i < len(images) else None
            label.setText(os.path.basename(p) if p else "（默认）")

    def _on_pick_balloon_image(self, idx):
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择注水 {[0, 25, 50, 100][idx]}% 的外观图",
            "", "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if not path:
            return
        # 与皮肤上传一致：圆形截取框 + 十字移动 + 右键重置
        from .crop_dialog import CropDialog
        dlg = CropDialog(path, self)
        if dlg.exec():
            images = list(self.cfg.get("balloon", {}).get("images") or [None] * 4)
            while len(images) < 4:
                images.append(None)
            images[idx] = dlg.cropped_path
            self.cfg["balloon"]["images"] = images
            self.ctrl.config["balloon"]["images"] = images
            from .config import save
            save(self.ctrl.config)
            self._refresh_balloon_images()
            for w in self.ctrl.balloon_windows:
                w.update()

    def _on_clear_balloon_image(self, idx):
        images = list(self.cfg.get("balloon", {}).get("images") or [None] * 4)
        while len(images) < 4:
            images.append(None)
        images[idx] = None
        self.cfg["balloon"]["images"] = images
        self.ctrl.config["balloon"]["images"] = images
        from .config import save
        save(self.ctrl.config)
        self._refresh_balloon_images()
        for w in self.ctrl.balloon_windows:
            w.update()

    def _update_water_label(self):
        self.water_value.setText(f"{self.cfg['balloon']['water']}%")

    def _on_water(self, v):
        self.cfg["balloon"]["water"] = int(v)
        self._update_water_label()
        self.ctrl.apply_water()
