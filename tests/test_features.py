# -*- coding: utf-8 -*-
"""Functional smoke test for the polished features (run on the live desktop)."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from desktop_pet.app import PetApp, MODE_BALLOON
from desktop_pet.config import save, set_config_dir
import tempfile
set_config_dir(tempfile.mkdtemp(prefix="dsh_test_"))   # 隔离：不触碰真实配置

failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(name)
        print(f"FAIL {name} {detail}")
    else:
        print(f"ok   {name}")


def main():
    qapp = QApplication(sys.argv)
    app = PetApp(qapp)
    check("startup mode is record/idle", app.mode == "idle", app.mode)

    # 1) record double-click: no audio -> refused; with audio -> play+rotate
    # (sync_external must be OFF so the test exercises LOCAL playback and
    #  does not fire real system media keys)
    saved_audio = app.config["record"].get("audio_path")
    saved_playlist = list(app.config["record"].get("playlist") or [])
    saved_sync = app.config["record"].get("sync_external", True)
    app.config["record"]["sync_external"] = False
    app.config["record"]["audio_path"] = None
    app.config["record"]["playlist"] = []
    app.on_record_double_click()
    check("record refused without audio", not app._record_playing)
    test_wav = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "sounds", "record_test.wav")
    import shutil
    shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "sounds", "slap.wav"), test_wav)
    app.config["record"]["audio_path"] = test_wav
    app.on_record_double_click()
    check("record plays with audio", app._record_playing)
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    check("record rotates", app._record_angle > 0, f"angle={app._record_angle}")
    app.on_record_double_click()
    check("record pauses on second click", not app._record_playing)
    if app.launch_player is not None:
        app.launch_player.stop()
        app.launch_player.setSource(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl())
    if app.music_player is not None:
        app.music_player.stop()
        app.music_player.setSource(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl())
    time.sleep(0.3)
    qapp.processEvents()
    os.remove(test_wav)
    # restore the original record config (no test pollution)
    app.config["record"]["audio_path"] = saved_audio
    app.config["record"]["playlist"] = saved_playlist
    app.config["record"]["sync_external"] = saved_sync
    save(app.config)

    # 2) balloon explosion: -1 then auto-refill +1 (count unchanged), +2 score
    app.config["balloon"]["score"] = 0
    save(app.config)
    app.switch_mode(MODE_BALLOON)
    time.sleep(0.3)
    qapp.processEvents()
    n0 = len(app.balloon_windows)
    w0 = app.balloon_windows[0]
    app.on_balloon_explode(w0)
    time.sleep(0.3)
    qapp.processEvents()
    check("explosion refills balloon", len(app.balloon_windows) == n0,
          f"{n0} -> {len(app.balloon_windows)} (explode then auto-refill)")
    check("explosion scores +2", app.config["balloon"]["score"] == 2,
          str(app.config["balloon"]["score"]))
    check("explosion effect spawned", len(app._balloon_effects) == 1)

    # 3) staggered pong respawn: one ball every interval (test uses 0.5s)
    app.config["pong"]["ball_count"] = 3
    app.config["pong"]["ball_speed"] = 100   # slow balls: few die during the test
    app.config["pong"]["spawn_interval"] = 0.5
    save(app.config)
    app.switch_mode("pong")
    time.sleep(0.2)
    qapp.processEvents()
    for b in list(app.pong.balls):
        app.pong.balls.remove(b)
    for w in list(app.ball_windows):
        w.close()
        app.ball_windows.remove(w)
    app._pong_pending = 0
    t0 = time.monotonic()
    while time.monotonic() < t0 + 1.2:
        qapp.processEvents()
        time.sleep(0.005)
    check("staggered: 2 balls after 1.2s", len(app.pong.balls) == 2,
          str(len(app.pong.balls)))
    while time.monotonic() < t0 + 2.6:
        qapp.processEvents()
        time.sleep(0.005)
    check("staggered: pending exhausted by 2.6s", app._pong_pending == 0,
          f"pending={app._pong_pending}")
    check("staggered: at least 2 alive", len(app.pong.balls) >= 2,
          f"{len(app.pong.balls)} alive (some may have died in play)")

    qapp.quit()
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        return 1
    print("\nALL FEATURE SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
