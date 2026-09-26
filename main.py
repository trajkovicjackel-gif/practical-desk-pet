# -*- coding: utf-8 -*-
"""Entry point for the Desktop Pet.

Usage:
    python main.py                     # normal run
    python main.py --selftest          # drive all modes, save screenshots, exit
    python main.py --selftest --shot-dir <dir>
"""

import argparse
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="桌面悬浮桌宠")
    parser.add_argument("--selftest", action="store_true",
                        help="drive all three modes and capture screenshots")
    parser.add_argument("--shot-dir", default=None,
                        help="directory for self-test screenshots")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication
    from desktop_pet.app import PetApp
    from desktop_pet.config import config_dir, set_config_dir

    if args.selftest:
        # 自测使用隔离配置目录，不触碰用户真实配置
        import tempfile
        set_config_dir(tempfile.mkdtemp(prefix="dsh_selftest_"))

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("DesktopPet")
    # 桌宠窗口均为 Qt.Tool，设置面板是唯一普通窗口：关闭设置面板不得退出
    # 程序（否则触发 Qt 默认 quitOnLastWindowClosed 行为）
    qapp.setQuitOnLastWindowClosed(False)
    app = PetApp(qapp)

    if args.selftest:
        shot_dir = args.shot_dir or os.path.join(config_dir(), "selftest")
        os.makedirs(shot_dir, exist_ok=True)

        def pump(seconds):
            """Let the Qt event loop actually run (timers fire)."""
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                qapp.processEvents()
                time.sleep(0.005)

        for mode_name in ("pong", "basketball", "balloon"):
            app.switch_mode(mode_name)
            pump(1.2)
            _shot(qapp, os.path.join(shot_dir, f"shot_{mode_name}_1.png"))
            pump(1.0)
            _shot(qapp, os.path.join(shot_dir, f"shot_{mode_name}_2.png"))

        # app-level scoring path checks
        results = app.selftest_scores()
        all_ok = True
        for name, ok in results:
            print(("PASS " if ok else "FAIL ") + name, flush=True)
            all_ok = all_ok and ok

        print("SELFTEST_DONE " + shot_dir, flush=True)
        print("SELFTEST_RESULT " + ("PASS" if all_ok else "FAIL"), flush=True)
        qapp.quit()
        return 0 if all_ok else 2

    app.qapp.exec()
    return 0


def _shot(qapp, path):
    screen = qapp.primaryScreen()
    pix = screen.grabWindow(0)
    pix.save(path)
    print("shot:", path, flush=True)


if __name__ == "__main__":
    sys.exit(main())
