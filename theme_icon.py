# -*- coding: utf-8 -*-
"""
主题化图标(theme_icon):用单色 SVG + 主题色染色的统一图标方案。

**为什么这么做**:UI 大量用 emoji(🧩📦🎨…),依赖系统 emoji 字体、跨平台/深浅底观感不一、
不够极简。方案 = 内置一套单色线框 SVG(icons/*.svg),渲染成 QIcon 后用主题色(current_color)
染色 → 深浅色 / 自定义主题 / 色盲模板 下图标自动跟随,风格统一、极简。

**用法**:
    from theme_icon import theme_icon
    # label.setPixmap(theme_icon("mod", 20))          → QIcon
    # btn.setIcon(theme_icon("shader", 18))           → QIcon
    # 左菜单:LeftMenu.add_item(label, icon="mod")     → QIcon(见 left_menu)

**颜色来源**:默认取 `current_color("accent")`;也可传具体色。缓存按 (name,size,color) 键,
主题换色时调 `recolor_icons()` 清缓存,图标颜色立即跟随。
"""
import os
import threading

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 图标库目录(源码运行:项目根 icons/;打包后:PyInstaller data 打进同路径)
_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

# 内置兜底:即使 icons/ 目录文件缺失(或未打进 exe),这些内嵌 SVG 仍可用。
# 键 = 图标名。同 icons/*.svg 里的文件同名会优先用文件(文件更易编辑)。
_EMBEDDED = {
    "mod": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M12 3 9 5.6 5.2 4.4 3.6 8 5 11.8 3.6 15.6 5.2 19.2 9 18 12 20.6 15 18 18.8 19.2 '
            '20.4 15.6 19 11.8 20.4 8 18.8 4.4 15 5.6Z"/><path d="M12 9.2a2.8 2.8 0 1 0 0 5.6 '
            '2.8 2.8 0 0 0 0-5.6Z"/></svg>'),
    "shader": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
               '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4'
               'M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7'
               'M7.2 16.8l-1.7 1.7"/></svg>'),
    "modpack": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M4 10.4 5.1 5.8A1.3 1.3 0 0 1 6.4 4.8h11.2a1.3 1.3 0 0 1 1.3 1l1.1 4.6"/>'
                '<path d="M6 10.4h12a1.4 1.4 0 0 1 1.4 1.4v5.4A1.6 1.6 0 0 1 17.8 18.8H6.2a1.6 1.6 0 '
                '0 1-1.6-1.6v-5.4A1.4 1.4 0 0 1 6 10.4Z"/><path d="M9 13.2h6"/></svg>'),
    "datapack": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                 'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                 '<rect x="4.6" y="3.4" width="14.8" height="17.2" rx="1.6"/><path d="M4.6 7.6h14.8"/>'
                 '<path d="M8 10.4h2.4M13.6 10.4h2.4M8 13.6h2.4M13.6 13.6h2.4"/></svg>'),
    "resourcepack": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                     'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                     '<rect x="4.6" y="4.6" width="14.8" height="14.8" rx="1.8"/>'
                     '<path d="M8 10.6a2.4 2.4 0 0 0 4.6 1 2.4 2.4 0 0 0 4.2 1.4 2.6 2.6 0 0 0 '
                     '2.6-2.6V9.6a7 7 0 0 0-7-7H9a4.4 4.4 0 0 0-4.4 4.4V9a2.6 2.6 0 0 0 1.4 2.3 '
                     '2.6 2.6 0 0 0 2-.7Z"/><path d="M9 7.6h.01M15 7.6h.01"/></svg>'),
    "utility": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M12 3.2 2.6 8.6 12 14l9.4-5.4Z"/>'
                '<path d="M5.4 11v5.2a1.4 1.4 0 0 0 .6 1.2l5 3a1.6 1.6 0 0 0 2 0l5-3a1.4 1.4 0 0 0 '
                '.6-1.2V11"/><path d="M12 14v6.4"/></svg>'),
    "running": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.6v4.4l3 2"/></svg>'),
    "download": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                 'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M12 4v10"/><path d="M7 10.5 12 15.5l5-5"/><path d="M4.5 19h15"/></svg>'),
    "favorite": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                 'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                 '<path d="M12 4.2l2.3 4.9 5.3.7-3.9 3.6 1 5.2-4.7-2.6-4.7 2.6 1-5.2-3.9-3.6 5.3-.7Z"/></svg>'),
    "loader": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
               '<circle cx="12" cy="12" r="3.4"/>'
               '<path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.2 5.2l1.7 1.7'
               'M17.1 17.1l1.7 1.7M18.8 5.2l-1.7 1.7M6.9 17.1l-1.7 1.7"/></svg>'),
    "settings": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                 'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                 '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.2M12 18.8V21M4.2 7.5l1.9 1.1'
                 'M17.9 15.4l1.9 1.1M4.2 16.5l1.9-1.1M17.9 8.6l1.9-1.1"/></svg>'),
    "ai": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           '<rect x="5" y="4.5" width="14" height="11.5" rx="2"/><path d="M9 20h6M12 16v4"/></svg>'),
    "home": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
             'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
             '<path d="M4 10.8 12 4.4l8 6.4"/>'
             '<path d="M5.6 9.4v9a1.2 1.2 0 0 0 1.2 1.2h3.4v-4.6a1.8 1.8 0 0 1 3.6 0v4.6h3.4a'
             '1.2 1.2 0 0 0 1.2-1.2v-9"/></svg>'),
    "instances": ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
                  'stroke="#000" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
                  '<rect x="4" y="4.5" width="7" height="7" rx="1.4"/>'
                  '<rect x="13.5" y="4.5" width="7" height="7" rx="1.4"/>'
                  '<rect x="4" y="13.5" width="7" height="7" rx="1.4"/>'
                  '<rect x="13.5" y="13.5" width="7" height="7" rx="1.4"/></svg>'),
}

_cache = {}
_cache_lock = threading.Lock()


def _load_svg(name: str) -> bytes | None:
    """取图标 SVG 字符串:优先 icons/<name>.svg 文件,回退内嵌表。"""
    # 文件优先(易编辑)
    try:
        path = os.path.join(_ICON_DIR, name + ".svg")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    except OSError:
        pass
    svg = _EMBEDDED.get(name)
    return svg.encode("utf-8") if svg else None


def _tint(svg_bytes: bytes, color: str, size: int) -> QPixmap:
    """渲染 SVG 到 pixmap,再用 color 染色(只保留 SVG 的 alpha 形状)。"""
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    src = QPixmap(size, size)
    src.fill(Qt.GlobalColor.transparent)
    p = QPainter(src)
    renderer.render(p)
    p.end()
    if src.isNull():
        return src

    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.fillRect(0, 0, size, size, QColor(color))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


def theme_icon(name: str, size: int = 20, color: str | None = None) -> QIcon:
    """主题化图标:按 (name,size,color) 缓存。color 缺省取 current_color('accent')。"""
    if color is None:
        try:
            from ui_style import current_color
            color = current_color("accent")
        except Exception:
            color = "#5B8DEF"
    key = (name, int(size), color)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    svg = _load_svg(name)
    if svg is None:
        return QIcon()
    pix = _tint(svg, color, int(size))
    icon = QIcon(pix)
    with _cache_lock:
        _cache[key] = icon
    return icon


def recolor_icons() -> None:
    """主题换色后清缓存:下次 theme_icon() 会用新色重建。"""
    with _cache_lock:
        _cache.clear()


def icon_names() -> list:
    """当前可用图标名(内嵌表 + icons/*.svg 文件)。"""
    names = set(_EMBEDDED.keys())
    try:
        for fn in os.listdir(_ICON_DIR):
            if fn.endswith(".svg"):
                names.add(fn[:-4])
    except OSError:
        pass
    return sorted(names)
