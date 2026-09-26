# -*- coding: utf-8 -*-
"""Targeted tests for the 10-item update batch (resume, sync, volume,
balloon inversion/alpha, vinyl px, calibration toasts). Live desktop needed.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QUrl, QPointF
from desktop_pet.app import PetApp, MODE_IDLE, MODE_BALLOON, MODE_BASKETBALL
from desktop_pet.config import save, load, set_config_dir
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


def main():
    qapp = QApplication(sys.argv)
    app = PetApp(qapp)

    saved_rec = app.config["record"].get("sync_external", True)
    saved_wav = app.config["record"].get("audio_path")
    saved_pl = list(app.config["record"].get("playlist") or [])
    saved_water = app.config["balloon"].get("water", 0)
    test_wav = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "sounds", "record_test.wav")

    # ── item 2: vinyl ring px control (50..350) + migration ──
    check("vinyl default 120px", app._vinyl_ring_r() == 120.0, str(app._vinyl_ring_r()))
    app.config["record"]["vinyl_ring_r"] = 400
    check("vinyl clamped to 350", app._vinyl_ring_r() == 350.0)
    app.config["record"]["vinyl_ring_r"] = 30
    check("vinyl clamped to 50", app._vinyl_ring_r() == 50.0)
    app.config["record"]["vinyl_ring_r"] = 120.0
    # migration: old vinyl_scale -> vinyl_ring_r
    old = {"mode": "idle", "record": {"vinyl_scale": 2.0},
           "appearance": {"radius": 80}}
    import json
    from desktop_pet import config as cfg_mod
    p = cfg_mod.config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(old, f)
    migrated = load()
    check("old vinyl_scale migrates to px",
          abs(migrated["record"]["vinyl_ring_r"] - 80 * 1.28 * 2.0) < 1.0,
          str(migrated["record"].get("vinyl_ring_r")))
    check("old vinyl_scale removed", "vinyl_scale" not in migrated["record"])
    save(app.config)  # rewrite clean config afterwards

    # ── item 6 + 3: sync mode = external only, animations still work ──
    app.config["record"]["sync_external"] = True
    app.config["record"]["audio_path"] = None
    app.config["record"]["playlist"] = []
    save(app.config)
    app.switch_mode(MODE_IDLE)
    pump(qapp, 0.3)
    # 同步模式下 _record_playing 会跟随外部播放器真实状态（SMTC 轮询），
    # 测试期间屏蔽轮询并重置状态，让内部状态决定动画（验证机制本身）
    import desktop_pet.smtc as _smtc_mod
    _saved_snapshot = _smtc_mod.snapshot
    _smtc_mod.snapshot = lambda: None
    app._record_playing = False
    app._record_angle = 0.0
    if app.idle_window is not None:
        app.idle_window.set_tonearm_engaged(False)
    app.on_record_double_click()
    check("sync: play works without local music", app._record_playing)
    check("sync: no local player created", app.music_player is None)
    app.record_next()
    check("sync: next does not create player", app.music_player is None)
    pump(qapp, 0.6)
    check("sync: animation keeps running (rotation advances)",
          app._record_angle > 0, f"angle={app._record_angle}")
    app.on_record_double_click()
    check("sync: second click pauses", not app._record_playing)
    _smtc_mod.snapshot = _saved_snapshot
    # toggle sync off with no music: animation must NOT work
    app.config["record"]["sync_external"] = False
    app.on_record_double_click()
    check("local: no music -> refused", not app._record_playing)

    # ── item 3 + 4 + 5: local playback, resume, volume, progress ──
    # 6-second 440Hz tone wav (real samples -> FFmpeg clock advances;
    # silence does not, and the user's mp3 is only 1.65s -> would loop)
    import wave
    import math as _math
    import struct as _struct
    with wave.open(test_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = bytearray()
        for i in range(44100 * 6):
            v = int(12000 * _math.sin(2 * _math.pi * 440 * i / 44100))
            frames += _struct.pack("<h", v)
        w.writeframes(bytes(frames))
    app.config["record"]["audio_path"] = test_wav
    save(app.config)
    app.on_record_double_click()
    check("local: starts playing", app._record_playing)
    check("local: player exists", app.music_player is not None)
    pump(qapp, 1.0)
    pos1 = app.music_player.position()
    check("local: position advanced", pos1 > 500, f"pos={pos1}")
    app.on_record_double_click()
    check("local: pauses", not app._record_playing)
    paused_pos = app.music_player.position()
    check("local: position kept on pause", paused_pos >= pos1,
          f"{pos1} -> {paused_pos}")
    # volume: left half must be audible (0..100 linear -> 0.0..1.0)
    app.record_set_volume(25)
    v25 = app.music_audio.volume()
    app.record_set_volume(80)
    v80 = app.music_audio.volume()
    check("volume 25 -> 0.25", abs(v25 - 0.25) < 0.01, str(v25))
    check("volume 80 -> 0.80", abs(v80 - 0.80) < 0.01, str(v80))
    check("volume left half not 0%", v25 > 0.01, str(v25))
    # progress bar signals: resume first, then the panel must show live time
    app.on_record_double_click()          # resume
    check("local: resumes from paused position", app._record_playing)
    pump(qapp, 0.5)
    app._show_record_panel()
    pump(qapp, 0.3)
    pnl = app.record_panel
    check("panel duration set", pnl.progress.maximum() > 0,
          f"max={pnl.progress.maximum()}")
    check("panel time label follows", pnl.time_cur.text() != "00:00",
          pnl.time_cur.text())
    check("local: position continued (not restarted from 0)",
          app.music_player.position() >= paused_pos - 50,
          f"{paused_pos} -> {app.music_player.position()}")
    app.on_record_double_click()
    check("local: pauses again", not app._record_playing)
    if app.music_player is not None:
        app.music_player.stop()
        app.music_player.setSource(QUrl())
    if app.launch_player is not None:
        app.launch_player.stop()
        app.launch_player.setSource(QUrl())
    pump(qapp, 0.3)
    os.remove(test_wav)

    # ── items 8 + 10: balloon water=0 at top; alpha cap 90% ──
    app.config["record"]["sync_external"] = saved_rec
    app.switch_mode(MODE_BALLOON)
    pump(qapp, 0.3)
    check("balloon: water defaults to 0", app.config["balloon"]["water"] == 0,
          str(app.config["balloon"]["water"]))
    if app.balloon_windows:
        fx, fy, fw, fh = app.field
        r = app.config["appearance"]["radius"]
        y0 = app.balloon_windows[0]._bposy
        check("balloon: floats near top", abs(y0 - (fy + r)) < 12, f"y={y0}")
    check("balloon: alpha at 0% = 0.10", app.balloon_visual(0)[2] == 0.10)
    check("balloon: alpha at 10% = 0.10", app.balloon_visual(10)[2] == 0.10)
    check("balloon: alpha at 50% = 0.50", app.balloon_visual(50)[2] == 0.50)
    check("balloon: alpha at 100% = 1.0", app.balloon_visual(100)[2] == 1.0)

    # ── item 9: calibration completes without re-prompting ──
    msgs = []
    app.tray.showMessage = lambda *a, **k: msgs.append(a)
    app.config["basketball"]["hoop_calibrated"] = False
    app.config["basketball"]["hoop_pos"] = None
    save(app.config)
    app.switch_mode(MODE_BASKETBALL)
    pump(qapp, 0.3)
    n_before = len(msgs)
    app.start_calibration()
    app._on_calibration_click(QPointF(400, 500))
    check("calibration enables hoop", app.hoop_enabled)
    app.switch_mode(MODE_IDLE)
    pump(qapp, 0.2)
    app.switch_mode(MODE_BASKETBALL)      # re-enter after calibration
    pump(qapp, 0.3)
    n_after = len(msgs)
    calib_msgs = [m for m in msgs if "校准" in str(m)]
    check("no extra calibration toast after re-entry",
          n_after == n_before + 1, f"{n_before} -> {n_after} ({calib_msgs})")
    app.config["balloon"]["water"] = saved_water
    save(app.config)
    app.switch_mode(MODE_IDLE)
    qapp.quit()
    print("FAILURES:", failures, flush=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
