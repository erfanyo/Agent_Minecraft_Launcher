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

from PySide6.QtWidgets import QPushButton, QListWidget, QToolButton, QTabWidget, QWidget


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
    # 先看 root 自身是否就是目标(如 rcswitch 切到的整页)
    if root is not None and (root.objectName() or "") == name:
        return root
    for w in root.findChildren(QWidget):
        if (w.objectName() or "") == name:
            return w
    return None


def _auto_switch_container(target, top):
    """把「左菜单+右面板」容器(有 .stack + .switch_to)的内部堆叠页,切到目标所在页。
    这样引导遮罩能框到**真正显示**的控件,而不是首页/错误页。"""
    if target is None:
        return
    # 从目标向上找最近的、有 stack+switch_to 的容器(如 ResourceCenter / CenterShell)
    # 目标本身若是该容器(如首页),不切。
    w = target
    while w is not None and w is not top:
        if hasattr(w, "stack") and hasattr(w, "switch_to"):
            stack = getattr(w, "stack")
            # 目标是不是该容器某个堆叠页里的控件(或就是该页)?
            for i in range(stack.count()):
                page = stack.widget(i)
                # 目标就是该页,或目标坐落在该页内(通过 parent 链上溯到 page)
                if page is target or _is_descendant(target, page):
                    if stack.currentIndex() != i:
                        try:
                            w.switch_to(i)
                        except Exception:
                            pass
                    return
        w = getattr(w, "parentWidget", lambda: None)() if hasattr(w, "parentWidget") else None
    # 兜底:目标本身是个 QStackedWidget 的当前页之外,不处理(交给 rcswitch 显式切)


def _is_descendant(widget, ancestor):
    """widget 是否是 ancestor 的后代(沿 parent 链上溯)。"""
    w = getattr(widget, "parentWidget", lambda: None)() if widget else None
    while w is not None:
        if w is ancestor:
            return True
        w = getattr(w, "parentWidget", lambda: None)() if hasattr(w, "parentWidget") else None
    return False


def resolve(main_window, route):
    """按 route 逐级解析到目标控件。返回 (target_widget, top_widget) 或 (None, None)。
    top_widget = 目标控件所在的最顶层窗口/容器(引导遮罩挂它上面)。

    解析完若目标在某个「左菜单+右面板」容器(如 ResourceCenter / CenterShell)内部,
    会自动把该容器的右侧堆叠页切到目标所在页,保证目标控件是**可见**的
    (否则引导遮罩会框在首页/错误的页上)。"""
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
        elif typ == "rcswitch":
            # 切当前控件(如 ResourceCenter)内部堆叠页,再取其当前页作为下一步目标
            if hasattr(cur, "switch_to"):
                cur.switch_to(int(key))
            cur = cur.stack.currentWidget() if hasattr(cur, "stack") else cur
        else:
            return None, None
    # 目标控件所在的最顶层窗口(引导遮罩挂它上面)
    top = cur.window()
    # 自动把「左菜单+右面板」容器的内部堆叠页,切到目标控件所在页(让目标可见)
    _auto_switch_container(cur, top)
    return cur, top
