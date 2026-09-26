# -*- coding: utf-8 -*-
"""Verify: recycle-bin ball file on score + SPACE slap edge trigger."""

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from desktop_pet.app import PetApp
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


def recycle_bin_has_ball():
    """Count 'ball' files in the Recycle Bin via Shell COM."""
    script = (
        "$sh = New-Object -ComObject Shell.Application; "
        "$rb = $sh.Namespace(10); "
        "$n = 0; "
        "foreach ($i in $rb.Items()) { if ($i.Name -eq 'ball') { $n++ } }; "
        "Write-Output $n"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=60)
    try:
        return int(out.stdout.strip())
    except ValueError:
        return -1


def main():
    qapp = QApplication(sys.argv)
    app = PetApp(qapp)

    # --- 1) recycle-bin ball file ---
    before = recycle_bin_has_ball()
    app.config["basketball"]["score"] = 0
    save(app.config)
    app._drop_ball_file_into_recycle_bin()
    time.sleep(1.0)
    after = recycle_bin_has_ball()
    check("recycle bin gains a 'ball' file", after == before + 1,
          f"{before} -> {after}")

    # --- 2) SPACE slap edge trigger ---
    app.switch_mode("basketball")
    app.config["basketball"]["hoop_calibrated"] = True
    app.config["basketball"]["hoop_pos"] = [300, 300]
    save(app.config)
    time.sleep(0.3)
    qapp.processEvents()
    import desktop_pet.app as appmod
    real_key_down = appmod._key_down
    appmod._key_down = lambda vk: True     # simulate SPACE held
    try:
        b = app.basket
        b.vy = 0.0
        app._space_down_prev = False
        app._tick_space_slap()             # rising edge -> slap
        vy1 = b.vy
        app._tick_space_slap()             # held (still down) -> no repeat
        vy2 = b.vy
        check("space rising edge slaps once", vy1 > 0, f"vy1={vy1}")
        check("space held does not repeat", vy2 == vy1, f"vy2={vy2} vs vy1={vy1}")
        app._space_down_prev = False       # key released then pressed again
        b.vy = 0.0
        app._tick_space_slap()
        vy3 = b.vy
        check("space second press slaps again", vy3 > 0, f"vy3={vy3}")
    finally:
        appmod._key_down = real_key_down

    qapp.quit()
    if failures:
        print(f"\n{len(failures)} FAILURES: {failures}")
        return 1
    print("\nALL FINAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
