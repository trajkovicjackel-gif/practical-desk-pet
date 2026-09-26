# -*- coding: utf-8 -*-
"""System Media Transport Controls (SMTC) bridge for external players.

同步外部音乐软件模式：通过 Windows 的 SMTC 会话读取外部播放器
（网易云/QQ音乐/Spotify/浏览器等）的播放状态与进度，并支持进度跳转。

多会话处理：系统里可能同时存在多个媒体会话（桌面播放器 + 浏览器标签），
get_current_session() 的返回并不可靠（可能指向浏览器而非用户桌面播放器）。
本模块支持：
  - set_selected("auto")：自动选择 —— 播放中的会话优先，其次最近更新的；
  - set_selected(app_id)：固定控制指定应用（设置面板中可选）。
winrt 未安装时自动降级（返回 None / False），不影响其他功能。
"""

import asyncio
import threading
import time

_manager = None
_available = None
_selected = "auto"     # "auto" 或 source_app_user_model_id


def available():
    """winrt-SMTC 是否可用（惰性检测）。"""
    global _available
    if _available is None:
        try:
            from winrt.windows.media.control import (  # noqa: F401
                GlobalSystemMediaTransportControlsSessionManager)
            _available = True
        except Exception:
            _available = False
    return _available


def _run(coro):
    try:
        return asyncio.run(coro)
    except Exception:
        return None


def set_selected(app_id):
    """指定要控制的外部播放器（"auto" = 自动选择）。"""
    global _selected
    _selected = app_id or "auto"


def get_selected():
    return _selected


def _manager_get():
    global _manager
    if not available():
        return None
    if _manager is None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager)
        _manager = _run(
            GlobalSystemMediaTransportControlsSessionManager.request_async())
    return _manager


def _valid_sessions():
    """返回 [(session, playback_info, timeline)]，仅有效的会话。"""
    mgr = _manager_get()
    if mgr is None:
        return []
    out = []
    try:
        for s in mgr.get_sessions():
            try:
                info = s.get_playback_info()
                tl = s.get_timeline_properties()
                if tl.end_time.total_seconds() > 0:
                    out.append((s, info, tl))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _session():
    """按选择策略返回目标会话：固定应用优先；auto = 播放中优先，其次
    最近更新（避免在多个会话间跳变导致面板闪烁）。"""
    v = _valid_sessions()
    if not v:
        return None
    if _selected != "auto":
        for s, _info, _tl in v:
            try:
                if (s.source_app_user_model_id or "") == _selected:
                    return s
            except Exception:
                continue
    playing = [t for t in v if int(t[1].playback_status) == 4]
    pool = playing or v
    return max(pool, key=lambda t: t[2].last_updated_time)[0]


def snapshot():
    """返回 (playing, pos_ms, dur_ms)；无外部会话时返回 None。"""
    s = _session()
    if s is None:
        return None
    try:
        playing = int(s.get_playback_info().playback_status) == 4
        return (playing, _pos_ms(s), _dur_ms(s))
    except Exception:
        return None


def list_sessions():
    """枚举当前媒体会话（设置面板用）；标题尽力而为（后台线程获取）。"""
    items = []
    threads = []
    for s, info, tl in _valid_sessions():
        item = {
            "app_id": s.source_app_user_model_id or "",
            "playing": int(info.playback_status) == 4,
            "pos_ms": int(tl.position.total_seconds() * 1000),
            "dur_ms": int(tl.end_time.total_seconds() * 1000),
            "title": "",
        }
        items.append(item)

        def fill(it, sess):
            it["title"] = _fetch_title(sess)

        th = threading.Thread(target=fill, args=(item, s), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(timeout=2)
    return items


def _pos_ms(session=None):
    """指定/当前会话的播放位置（毫秒）；无会话返回 None。"""
    s = session if session is not None else _session()
    if s is None:
        return None
    try:
        return int(s.get_timeline_properties().position.total_seconds() * 1000)
    except Exception:
        return None


def _dur_ms(session=None):
    s = session if session is not None else _session()
    if s is None:
        return None
    try:
        return int(s.get_timeline_properties().end_time.total_seconds() * 1000)
    except Exception:
        return None


def _smtc_seek(target_ms):
    s = _session()
    if s is None:
        return False
    ticks = int(max(0, target_ms)) * 10_000   # 100ns 刻度：1s = 10_000_000
    res = _run(s.try_change_playback_position_async(ticks))
    return bool(res)


def _near_target(target_ms, timeout=2.5):
    """轮询验证位置是否落在目标附近（容差 2s：精确跳转 ±2s 内）。

    注意容差不可随时长放大：失败跳转的位置只差“播放推进”几秒，
    过宽容差会让假成功蒙混过关（进度条回弹）。
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        time.sleep(0.25)
        now = _pos_ms()
        if now is None:
            continue
        if abs(now - target_ms) <= 2000:
            return True
    return False


def _target_window():
    """选中应用的主窗口（uiautomation）；失败返回 None。"""
    try:
        import subprocess
        import uiautomation as auto
        if _selected == "auto":
            s = _session()
            if s is None:
                return None
            app_id = s.source_app_user_model_id or ""
        else:
            app_id = _selected
        if not app_id:
            return None
        out = subprocess.check_output(
            f'tasklist /FI "IMAGENAME eq {app_id}" /FO CSV /NH',
            shell=True).decode("gbk", errors="ignore").strip()
        if not out:
            return None
        pid = int(out.split('","')[1])
        for w in auto.GetRootControl().GetChildren():
            try:
                if w.ProcessId == pid and w.ControlTypeName in (
                        "WindowControl", "PaneControl") and w.IsEnabled:
                    return w
            except Exception:
                continue
    except Exception:
        pass
    return None


def _uia_seek(target_ms):
    """UIA RangeValue 进度条（适用于暴露滑块的播放器）。"""
    try:
        win = _target_window()
        if win is None:
            return False
        dur = _dur_ms()
        if not dur:
            return False
        frac = max(0.0, min(1.0, target_ms / dur))

        def find(ctrl, depth):
            if depth > 6:
                return None
            for c in ctrl.GetChildren():
                try:
                    rv = c.GetRangeValuePattern()
                    if rv is not None and rv.MaximumValue > rv.MinimumValue:
                        rv.SetValue(rv.MinimumValue
                                    + (rv.MaximumValue - rv.MinimumValue) * frac)
                        return True
                except Exception:
                    pass
                if find(c, depth + 1):
                    return True
            return None

        return bool(find(win, 0))
    except Exception:
        return False



def seek(sec):
    """直接映射跳转到目标外部播放器的指定秒数（纯 API，不碰鼠标、
    后台窗口同样有效）。每级尝试后验证位置是否真正到达目标附近：
      1) SMTC try_change_playback_position_async —— 系统媒体会话直跳
         （Edge 浏览器 / Spotify / 网易云等支持 seek 的播放器）
      2) UIA RangeValue 滑块 —— 暴露滑块的播放器
    注意：部分播放器（如 QQ音乐）的 SMTC 会话为只读，不接受任何跳转，
    这是播放器自身行为，Windows 系统层面没有可用的替代 API；
    此类播放器会保持只读显示（进度照常展示），跳转后进度条回弹。
    本函数会阻塞数秒（含验证），请在后台线程调用。
    """
    target_ms = int(float(sec) * 1000)
    before = _pos_ms()
    if before is None:
        return False
    if abs(target_ms - before) < 1500:
        return True                      # 目标与当前位置几乎一致
    if _smtc_seek(target_ms) and _near_target(target_ms):
        return True
    if _uia_seek(target_ms) and _near_target(target_ms):
        return True
    return False


def _fetch_title(session):
    """在工作线程中获取会话标题（规避 Qt 事件循环内 asyncio.run 失败）。"""
    try:
        props = _run(session.try_get_media_properties_async())
        return (props.title or "") if props is not None else ""
    except Exception:
        return ""


def title():
    """当前选中会话的媒体标题；无会话或不可用返回空串。"""
    s = _session()
    if s is None:
        return ""
    res = []

    def worker():
        res.append(_fetch_title(s))

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(timeout=5)
    return res[0] if res else ""
