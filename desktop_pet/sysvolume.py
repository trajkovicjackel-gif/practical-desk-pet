# -*- coding: utf-8 -*-
"""绝对系统音量控制（Core Audio API）。

通过 pycaw（IAudioEndpointVolume）直接读取/设置 Windows 主音量：
最左 0% = 静音，最右 100% = 满音量，任意当前值都会被覆盖。
pycaw 未安装或调用失败时自动降级（get 返回 None、set 返回 False），
由调用方回退到相对音量键。
"""

_vol = None          # None=未初始化, False=不可用, 其他=接口
_checked = False


def _ensure():
    global _vol, _checked
    if _checked:
        return _vol
    _checked = True
    try:
        from pycaw.pycaw import AudioUtilities
        _vol = AudioUtilities.GetSpeakers().EndpointVolume
    except Exception:
        _vol = False
    return _vol


def available():
    return _ensure() is not False


def get():
    """当前系统主音量 0.0..1.0；不可用时返回 None。"""
    v = _ensure()
    if not v:
        return None
    try:
        return float(v.GetMasterVolumeLevelScalar())
    except Exception:
        return None


def set(fraction):
    """设置系统主音量为 0.0..1.0（绝对覆盖）。成功返回 True。"""
    v = _ensure()
    if not v:
        return False
    try:
        v.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(fraction))), None)
        return True
    except Exception:
        return False
