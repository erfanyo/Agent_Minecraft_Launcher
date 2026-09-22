# -*- coding: utf-8 -*-
"""Mod 列表的显示助手:一个圆点 + 文件名,供服务端/客户端详情共用。

**为什么单独抽出来**:服务端详情与客户端实例详情都要列 mods,并且都要表达
「启用 / 停用」这一个二态。两处各写一遍必然漂移,所以状态 → 圆点/文案的映射
只在这里维护一次。

圆点取自 :func:`theme_icon.status_dot`,颜色按语义取主题色(success/danger),
因此跟随深浅主题与色盲模板——不用 emoji 🟢/🔴(那些依赖系统 emoji 字体)。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QListWidgetItem

from theme_icon import status_dot
from ui_style import danger_color, success_color

#: 圆点在列表里的显示尺寸
DOT_SIZE = 12
#: 圆点与文件名之间的间距。QListWidget 不控制图标与文字的间距,用两个空格近似;
#: 再宽会在长文件名上浪费横向空间,再窄会贴住圆点。
DOT_GAP = '  '

STATE_ENABLED = '启用'
STATE_DISABLED = '已停用'


def is_disabled(filename: str) -> bool:
    """按 .jar / .jar.disabled 判定是否停用(与 set_server_mod_enabled 的规则一致)。"""
    return str(filename or '').lower().endswith('.disabled')


def state_text(filename: str) -> str:
    return STATE_DISABLED if is_disabled(filename) else STATE_ENABLED


def is_mod_file(filename: str) -> bool:
    return str(filename or '').lower().endswith(('.jar', '.jar.disabled'))


def listable_mods(directory: str, *, skip_links: bool = True) -> list:
    """列出目录下可显示的 mod 文件名(已排序);目录不存在返回空列表。"""
    if not directory or not os.path.isdir(directory):
        return []
    names = []
    for name in sorted(os.listdir(directory)):
        if not is_mod_file(name):
            continue
        path = os.path.join(directory, name)
        if skip_links and os.path.islink(path):
            continue
        if not os.path.isfile(path):
            continue
        names.append(name)
    return names


def make_item(filename: str) -> QListWidgetItem:
    """构造一个列表项:绿点=启用 / 红点=已停用,文字为文件名。

    颜色语义取 success/danger,不写死色值(色值扫描要求,也便于主题跟随)。
    悬停提示里补一句状态文字,方便色觉障碍用户或截图看不清颜色时确认。
    """
    disabled = is_disabled(filename)
    color = danger_color() if disabled else success_color()
    item = QListWidgetItem(
        status_dot(color, DOT_SIZE), f'{DOT_GAP}{filename}')
    item.setToolTip(f'{filename}\n状态：{state_text(filename)}'
                    + ('（文件名以 .disabled 结尾）' if disabled else ''))
    # 圆点只是标记,不要让它抢走选中语义
    item.setData(Qt.ItemDataRole.UserRole, filename)
    return item


def fill(list_widget, directory: str, *, empty_text: str = '(没有 mods 目录)'):
    """把目录下的 mods 填进列表控件;返回填入数量。"""
    names = listable_mods(directory)
    list_widget.clear()
    if not names:
        list_widget.addItem(QListWidgetItem(empty_text))
        return 0
    for name in names:
        list_widget.addItem(make_item(name))
    list_widget.setIconSize(QSize(DOT_SIZE, DOT_SIZE))
    return len(names)
