# -*- coding: utf-8 -*-
"""Targeted tests for the 5-item fix batch (antenna, settings-close, pause
angle, external SMTC volume/progress, folder import)."""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QRegion, QImage
from PySide6.QtWidgets import QWidget as _QWidget
from desktop_pet.app import PetApp, MODE_IDLE
from desktop_pet.config import save, set_config_dir
import tempfile
set_config_dir(tempfile.mkdtemp(prefix="dsh_test_"))   # 隔离：不触碰真实配置

failures = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name, detail, flush=True)
    if not cond:
        failures.append(name)


def pump(qapp, sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)


def render(win):
    img = QImage(win.width(), win.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    win.render(img, QPoint(0, 0), QRegion(), _QWidget.RenderFlag.DrawChildren)
    return img


def main():
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)   # 与 main.py 保持一致
    app = PetApp(qapp)

    saved_rec = app.config["record"].get("sync_external", True)
    saved_wav = app.config["record"].get("audio_path")
    saved_pl = list(app.config["record"].get("playlist") or [])
    test_wav = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "sounds", "record_test.wav")
    import wave
    with wave.open(test_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = bytearray()
        for i in range(44100 * 6):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / 44100))
            frames += __import__("struct").pack("<h", v)
        w.writeframes(bytes(frames))

    # ── item 1: no antenna (cueing lever) — render for vision check ──
    app.switch_mode(MODE_IDLE)
    pump(qapp, 0.8)
    win = app.idle_window
    img = render(win)
    img.save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "selftest", "shot_no_antenna.png"))
    check("item1: render saved for vision check", not img.isNull())

    # ── item 2: closing settings 5x does not quit the app ──
    quit_flag = []
    qapp.aboutToQuit.connect(lambda: quit_flag.append(1))
    for i in range(5):
        app.open_settings()
        pump(qapp, 0.2)
        check(f"item2: settings open #{i}", app.settings is not None
              and app.settings.isVisible())
        app.settings.close()
        pump(qapp, 0.2)
        check(f"item2: settings closed #{i}, app alive",
              not quit_flag and app.idle_window is not None
              and app.idle_window.isVisible())
    check("item2: no quit after 5 open/close cycles", not quit_flag)

    # ── item 3: pause keeps rotation angle ──
    # 清掉 SMTC 轮询可能遗留的“外部在播放”状态，保证本地路径确定性
    app.config["record"]["sync_external"] = False
    app._record_playing = False
    app._record_angle = 0.0
    if app.idle_window is not None:
        app.idle_window.set_rotation(0.0)
        app.idle_window.set_tonearm_engaged(False)
    app.config["record"]["audio_path"] = test_wav
    app.config["record"]["playlist"] = []
    save(app.config)
    app.on_record_double_click()          # play (local)
    pump(qapp, 1.2)
    ang_playing = app._record_angle
    rot_playing = app.idle_window.rotation_angle
    check("item3: playing angle > 0", ang_playing > 0, f"angle={ang_playing}")
    app.on_record_double_click()          # pause
    pump(qapp, 0.5)
    check("item3: angle kept on pause (not reset to 0)",
          app._record_angle > 0 and app.idle_window.rotation_angle == rot_playing,
          f"angle={app._record_angle} rot={app.idle_window.rotation_angle}")
    if app.music_player is not None:
        app.music_player.stop()
        app.music_player.setSource(__import__("PySide6.QtCore",
                                              fromlist=["QUrl"]).QUrl())
    pump(qapp, 0.3)

    # ── item 4: SMTC snapshot + volume throttling routing ──
    from desktop_pet import smtc
    check("item4: smtc available", smtc.available())
    snap = smtc.snapshot()                # 只读探测，不打扰外部播放
    check("item4: snapshot returns None or (playing,pos,dur)",
          snap is None or (len(snap) == 3 and isinstance(snap[0], bool)
                           and isinstance(snap[1], int) and isinstance(snap[2], int)),
          str(snap))
    # 音量：同步模式 → 绝对系统音量（打桩 set，不真正改系统音量）
    app.config["record"]["sync_external"] = True
    import desktop_pet.sysvolume as sv_mod
    sv_calls = []
    sv_mod.set = lambda f: (sv_calls.append(float(f)), True)[1]
    app._vol_last = None
    app._vol_last_t = 0.0
    app.record_set_volume(30)
    app.record_set_volume(90)
    app.record_set_volume(90)
    check("item4: absolute volume set called with 0.3/0.9/0.9",
          sv_calls == [0.3, 0.9, 0.9], str(sv_calls))
    # 绝对音量不可用 → 兜底相对音量键（节流 100ms 需间隔）
    keys = []
    app._send_media_key = lambda vk: keys.append(vk)
    sv_mod.set = lambda f: False
    app._vol_last = None
    app._vol_last_t = 0.0
    app.record_set_volume(30)             # 80→30：VOL_DOWN
    time.sleep(0.15)
    app.record_set_volume(90)             # 30→90：VOL_UP
    time.sleep(0.15)
    app.record_set_volume(90)             # 无变化：不发键
    check("item4: fallback volume keys when absolute unavailable",
          app.VK_VOLUME_DOWN in keys and app.VK_VOLUME_UP in keys,
          [hex(k) for k in keys])
    n_up = keys.count(app.VK_VOLUME_UP)
    check("item4: no keys when value unchanged",
          keys.count(app.VK_VOLUME_DOWN) >= 1 and n_up >= 1 and len(keys) >= 2,
          f"keys={[hex(k) for k in keys]}")
    # 进度条 seek 路由：同步模式 → smtc_seek（打桩）
    seeked = []
    app.smtc_seek = lambda sec: seeked.append(sec)
    app._show_record_panel()
    pump(qapp, 0.2)
    pnl = app.record_panel
    pnl.progress.setRange(0, 200)
    pnl.progress.setValue(42)
    pnl._on_release()
    check("item4: seek routed to smtc in sync mode", seeked == [42], str(seeked))
    # 外部进度显示
    pnl.sync_external_progress(True, 65000, 240000)
    check("item4: external progress shown (01:05 / 04:00)",
          pnl.time_cur.text() == "01:05" and pnl.time_total.text() == "04:00"
          and pnl.progress.maximum() == 240,
          f"{pnl.time_cur.text()}/{pnl.time_total.text()}/{pnl.progress.maximum()}")

    # ── item 5: folder import (folder scan + merge) ──
    import tempfile
    from desktop_pet.settings_dialog import SettingsDialog
    folder = tempfile.mkdtemp(prefix="pet_pl_")
    sub = os.path.join(folder, "子目录")
    os.makedirs(sub)
    files = []
    for name in ("a.mp3", "b.flac", "c.wav"):
        p = os.path.join(folder, name)
        open(p, "w").close()
        files.append(p)
    sub_file = os.path.join(sub, "d.ogg")
    open(sub_file, "w").close()
    open(os.path.join(folder, "note.txt"), "w").close()
    scanned = SettingsDialog.scan_audio_files(folder)
    check("item5: recursive scan finds 4 audio files", len(scanned) == 4,
          str([os.path.basename(s) for s in scanned]))
    check("item5: txt excluded", all(not s.endswith(".txt") for s in scanned))
    # 一键导入（打桩文件对话框）
    dlg = SettingsDialog(app)
    import desktop_pet.settings_dialog as sd_mod
    sd_mod.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: folder)
    dlg._on_import_folder()
    pl = app.config["record"]["playlist"]
    check("item5: playlist merged all 4", len(pl) == 4 and sub_file in pl,
          str([os.path.basename(p) for p in pl]))
    dlg._on_import_folder()               # 再导入一次：去重
    check("item5: re-import deduplicates", len(app.config["record"]["playlist"]) == 4)
    dlg.close()
    import shutil
    shutil.rmtree(folder, ignore_errors=True)

    # cleanup
    os.remove(test_wav)
    app.config["record"]["audio_path"] = saved_wav
    app.config["record"]["playlist"] = saved_pl
    app.config["record"]["sync_external"] = saved_rec
    save(app.config)
    app.switch_mode(MODE_IDLE)
    qapp.quit()
    print("FAILURES:", failures, flush=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
