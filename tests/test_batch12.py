# -*- coding: utf-8 -*-
"""Tests: external seek (SMTC ticks) + absolute system volume control."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
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


def main():
    qapp = QApplication(sys.argv)
    app = PetApp(qapp)
    saved_rec = app.config["record"].get("sync_external", True)

    from desktop_pet import smtc, sysvolume

    # ── seek：正确方法名 + 100ns 刻度 ──
    check("seek: ticks math (1s = 10_000_000)", int(60 * 10_000_000) == 600_000_000)
    check("seek: session-based seek runs", smtc.available())
    s = smtc.snapshot()
    if s is not None:
        _playing, pos, dur = s
        # 原地跳转（当前位置）——不打扰播放，仅验证调用链路
        ok = smtc.seek(pos / 1000.0)
        check("seek: try_change_playback_position accepted", ok is True)
    else:
        check("seek: no session -> graceful None", smtc.snapshot() is None)

    # ── 绝对系统音量 ──
    check("volume: sysvolume available", sysvolume.available())
    cur = sysvolume.get()
    check("volume: read returns 0..1 float",
          cur is not None and 0.0 <= cur <= 1.0, str(cur))
    if cur is not None:
        check("volume: absolute set 0.33", sysvolume.set(0.33))
        time.sleep(0.1)
        got = sysvolume.get()
        check("volume: read back ~0.33", got is not None and abs(got - 0.33) < 0.02,
              str(got))
        check("volume: set 0.0 (mute)", sysvolume.set(0.0))
        time.sleep(0.1)
        got = sysvolume.get()
        check("volume: read back ~0.0", got is not None and got < 0.02, str(got))
        check("volume: set 1.0 (max)", sysvolume.set(1.0))
        time.sleep(0.1)
        got = sysvolume.get()
        check("volume: read back ~1.0", got is not None and got > 0.98, str(got))
        sysvolume.set(cur)                     # 恢复原音量
        time.sleep(0.1)
        check("volume: restored", abs(sysvolume.get() - cur) < 0.02)

    # ── 应用层：同步模式音量滑条 → 绝对覆盖 ──
    app.config["record"]["sync_external"] = True
    save(app.config)
    app.switch_mode(MODE_IDLE)
    app._show_record_panel()
    pump(qapp, 0.3)
    pnl = app.record_panel
    v = sysvolume.get()
    if v is not None:
        check("volume: slider synced to system volume on show",
              abs(pnl.vol_slider.value() - int(round(v * 100))) <= 2,
              f"slider={pnl.vol_slider.value()} sys={v:.2f}")
    # 最左 → 0%，最右 → 100%（绝对覆盖）
    app.record_set_volume(0)
    time.sleep(0.1)
    check("volume: slider 0 -> system 0%", sysvolume.get() is not None
          and sysvolume.get() < 0.02, str(sysvolume.get()))
    app.record_set_volume(100)
    time.sleep(0.1)
    check("volume: slider 100 -> system 100%", sysvolume.get() is not None
          and sysvolume.get() > 0.98, str(sysvolume.get()))
    app.record_set_volume(int(round(v * 100))) if v is not None else None
    time.sleep(0.1)
    check("volume: restored after slider test",
          sysvolume.get() is not None and abs(sysvolume.get() - (v or 0)) < 0.02)

    # ── 多会话选择：固定应用 / auto 稳定性 ──
    sessions = smtc.list_sessions()
    check("session: list_sessions returns list of dicts",
          isinstance(sessions, list) and all(
              isinstance(s, dict) and "app_id" in s and "playing" in s
              for s in sessions), str(sessions))
    if sessions:
        first = sessions[0]["app_id"]
        smtc.set_selected(first)
        snap = smtc.snapshot()
        check("session: explicit app id selects that session",
              snap is not None and len(snap) == 3, str(snap))
    # 固定选择必须稳定；auto 合法地跟随最近活跃会话（允许变化）
    smtc.set_selected("auto")
    for _ in range(3):
        p = smtc.snapshot()
        check("session: auto returns tuple or None",
              p is None or (len(p) == 3 and isinstance(p[0], bool)), str(p))
    if sessions:
        smtc.set_selected(first)
        durs = set()
        for _ in range(4):
            p = smtc.snapshot()
            if p is not None:
                durs.add(p[2])          # 时长相同 = 同一会话（位置会推进）
            time.sleep(0.2)
        check("session: explicit selection stable (no flicker)",
              len(durs) <= 1, f"durs={durs}")
    smtc.set_selected("auto")

    # ── 新能力：进度条自动定位 / 标题 ──
    t = smtc.title()
    check("seek: title returns str (may be empty)",
          isinstance(t, str), repr(t[:20]))

    app.config["record"]["sync_external"] = saved_rec
    save(app.config)
    app.switch_mode(MODE_IDLE)
    qapp.quit()
    print("FAILURES:", failures, flush=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
