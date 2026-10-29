# -*- coding: utf-8 -*-
"""主窗口几何(尺寸 + 位置)的保存与恢复。

**为什么单独一个模块**:这类逻辑最容易长出边界问题——把窗口恢复到一块已经拔掉的
显示器上、把最大化状态当成尺寸存下来、或者第一次启动时随便挑一个和屏幕不搭的
默认值。这些都能用纯函数表达并单测,所以这里不碰 Qt 窗口,只做数据与校验;
真正 `setGeometry` 的部分留在 ``main`` 里。

约定:
- 只保存**普通状态**的几何;最大化/最小化/全屏不写入,否则「记住大小」会退化成
  「每次都最大化」,用户再想还原也没了目标尺寸。
- 恢复时若窗口落在当前所有屏幕之外(换显示器/拔外接屏),丢弃位置只保留尺寸,
  以免窗口跑到看不见的地方。
- 保存的是相对主屏可再用区域的规范化值更稳,但 Qt 全局坐标已足够,这里保持简单:
  存原始 x/y/w/h,恢复时做可见性校验。
"""
from __future__ import annotations

SETTINGS_KEY = 'window_geometry'

#: 首次启动(或用户点「恢复默认尺寸」)时的窗口尺寸。
DEFAULT_SIZE = (1280, 860)
#: 窗口不得小于主窗口自己的最小尺寸(见 MainWindow.setMinimumSize)。
MIN_SIZE = (700, 560)


def sanitize(geom) -> dict | None:
    """校验并规范化一份几何数据;不合法返回 None。

    接受 ``{'x','y','w','h'}``(数字)。宽高必须为正且不小于 MIN_SIZE 才算数;
    坐标允许为负(多屏时副屏在主屏左侧很常见),不做限制,可见性交给
    :func:`restore_target` 判断。
    """
    if not isinstance(geom, dict):
        return None
    try:
        x, y = int(geom['x']), int(geom['y'])
        w, h = int(geom['w']), int(geom['h'])
    except (KeyError, TypeError, ValueError):
        return None
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        return None
    return {'x': x, 'y': y, 'w': w, 'h': h}


def capture(window) -> dict | None:
    """从窗口读一份可保存的几何;最大化/最小化/全屏时返回 None(不覆盖旧值)。"""
    try:
        if window.isMinimized() or window.isMaximized() or window.isFullScreen():
            return None
        rect = window.geometry()
    except (AttributeError, RuntimeError):
        return None
    return sanitize({'x': rect.x(), 'y': rect.y(),
                     'w': rect.width(), 'h': rect.height()})


def _visible_on_any_screen(geom: dict, screens) -> bool:
    """窗口是否与任一屏幕有足够重叠(至少露出标题栏那条)。"""
    if not screens:
        return True
    # 与任一块屏幕相交面积达到 40x40 就算看得见
    for screen in screens:
        try:
            area = screen.availableGeometry()
        except (AttributeError, RuntimeError):
            continue
        overlap_w = min(geom['x'] + geom['w'], area.x() + area.width()) - max(geom['x'], area.x())
        overlap_h = min(geom['y'] + geom['h'], area.y() + area.height()) - max(geom['y'], area.y())
        if overlap_w >= 40 and overlap_h >= 40:
            return True
    return False


def restore_target(saved, screens, primary=None) -> dict:
    """算出恢复窗口该用的几何 ``{'x','y','w','h'}``。

    - 没有可用记录 → 默认尺寸,并居中到主屏
    - 位置与所有屏幕都不相交 → **保留尺寸**,只把位置改为居中(用户挑过的
      尺寸是有意义的,换显示器不该顺带把尺寸也重置)
    - 尺寸超过屏幕可用区域 → 收敛到屏幕大小(避免够不到边)
    - 尺寸小于窗口最小尺寸 → 由 :func:`sanitize` 判为无效,回默认
    """
    primary_area = None
    if primary is not None:
        try:
            primary_area = primary.availableGeometry()
        except (AttributeError, RuntimeError):
            primary_area = None
    if primary_area is None and screens:
        primary_area = screens[0].availableGeometry()

    geom = sanitize(saved)
    if geom is None:
        return _centered(DEFAULT_SIZE, primary_area)

    size = _clamp_size(geom['w'], geom['h'], primary_area)
    if _visible_on_any_screen(geom, screens):
        return {'x': geom['x'], 'y': geom['y'], 'w': size[0], 'h': size[1]}
    return _centered(size, primary_area)


def _clamp_size(w: int, h: int, area) -> tuple:
    """把尺寸收敛到「屏幕可用区域」与「窗口最小值」之间。"""
    if area is None:
        return max(w, MIN_SIZE[0]), max(h, MIN_SIZE[1])
    return (max(MIN_SIZE[0], min(w, area.width())),
            max(MIN_SIZE[1], min(h, area.height())))


def _centered(size, area) -> dict:
    w, h = size
    if area is not None:
        w = min(w, area.width())
        h = min(h, area.height())
        x = area.x() + max(0, (area.width() - w) // 2)
        y = area.y() + max(0, (area.height() - h) // 2)
    else:
        x = y = 60
    return {'x': x, 'y': y, 'w': w, 'h': h}


def default_geometry(screens, primary=None) -> dict:
    """「恢复默认尺寸」的目标几何。"""
    return restore_target(None, screens, primary)
