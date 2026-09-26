# -*- coding: utf-8 -*-
"""Windows recycle-bin detection.

The Recycle Bin is a virtual shell folder; the only user-visible toggle is the
desktop icon. Windows stores that in the Explorer "HideDesktopIcons" registry
keys under the Recycle Bin CLSID. We also fall back to checking the classic
desktop icons key, and finally assume present (Windows always has one).
"""

import winreg

RECYCLE_BIN_CLSID = "{645FF040-5081-101B-9F08-00AA002F954E}"

_BASES = [
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel", "NewStartPanel"),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\ClassicDesktop", "ClassicDesktop"),
]


def recycle_bin_visible_on_desktop():
    """True when the Recycle Bin icon should be on the desktop.

    Registry value 1 under HideDesktopIcons/<CLSID> means "hidden" for that
    icon. Missing keys default to visible.
    """
    for subkey, _ in _BASES:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as k:
                try:
                    value, _ = winreg.QueryValueEx(k, RECYCLE_BIN_CLSID)
                    if value == 1:
                        return False
                except FileNotFoundError:
                    pass
        except OSError:
            continue
    return True
