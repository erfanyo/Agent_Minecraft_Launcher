# -*- coding: utf-8 -*-
"""
UI 路由解析器(引导式教程的"定位器"):把逻辑route解析成真实控件对象。

**为什么**:引导式教程要"指着真实 UI 每一步引导"。教程数据只写逻辑路由(如
`[("maintab","我的版本"), ("btn","启动游戏")]`),由这里运行时解析成具体控件;
UI 改了只需改 route 或注册表,不用改教程内容。

route 段格式 (类型, key):
- ("maintab", "我的版本"|"下载新资源"|"设置")  切换主标签页
- ("btn", 按钮文本)                            在父控件里找文本匹配/objectName 的按钮
- ("widgetname", "someName")                    按 objectName 找子孙控件
- ("sub", 索引)                                 取某个 child 控件(高级,少用)
"""
import os

from PySide6.QtWidgets import QPushButton, QListWidget, QToolButton, QTabWidget


def _find_button(root, label: str):
    """在 root 的子孙里找文本/objectName 含 label 的按钮(QPushButton/QToolButton)。"""
    label = (label or "").strip()
    for cls in (QPushButton, QToolButton):
        for b in root.findChildren(cls):
            txt = (b.text() or "").strip()
            name = (b.objectName() or "").strip()
            if txt == label or name == label or (label and label in txt):
                return b
    return None


def _find_by_objectname(root, name: str):
    for w in root.findChildren(object):
        if (w.objectName() or "") == name:
            return w
    return None


def resolve(main_window, route):
    """按 route 逐级解析到目标控件。返回 (target_widget, top_widget) 或 (None, None)。
    top_widget = 目标控件所在的最顶层窗口/容器(引导遮罩挂它上面)。"""
    cur = main_window
    for seg in route:
        if not isinstance(seg, (list, tuple)) or len(seg) != 2:
            continue
        typ, key = seg[0], seg[1]
        if typ == "maintab":
            tabs = getattr(main_window, "main_tabs", None)
            if tabs is None:
                return None, None
            idx = -1
            for i in range(tabs.count()):
                if tabs.tabText(i) == key:
                    idx = i
                    break
            if idx < 0:
                # 也允许按 widget 的 objectName 匹配
                for i in range(tabs.count()):
                    if (tabs.widget(i).objectName() or "") == key:
                        idx = i
                        break
            if idx < 0:
                return None, None
            tabs.setCurrentIndex(idx)
            cur = tabs.widget(idx)
        elif typ == "btn":
            cur = _find_button(cur, key)
            if cur is None:
                return None, None
        elif typ == "widgetname":
            cur = _find_by_objectname(cur, key)
            if cur is None:
                return None, None
        else:
            return None, None
    # 目标控件所在的最顶层窗口(引导遮罩挂它上面)
    return cur, cur.window()
