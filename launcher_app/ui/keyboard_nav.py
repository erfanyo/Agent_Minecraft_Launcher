# -*- coding: utf-8 -*-
"""
全局键盘导航框架(遥控器式):方向键切换菜单/标签,Enter 进入分项。

- 顶部分类标签(横向):← / → 切换;
- 页内左菜单(竖向):↑ / ↓ 切换菜单项;
- Enter:进入当前菜单的第 1 个分项;
- Esc:退回到菜单(预留)。

**安全原则(关键,防回归)**:
- 只有当【焦点不在任何"自己会处理按键"的交互控件】时才做导航。
  实例列表/资源列表/按钮/输入框等有它们自己的方向键/回车逻辑,焦点在它们上面时
  本框架放行,绝不抢键(否则会跟实例列表的"上下选实例+回车启动"打架)。
- 所以这里判断的是"焦点控件是否自己消费方向键/回车"→ 是则不导航。

用法(MainWindow 初始化后):
    from keyboard_nav import install_global_nav
    install_global_nav(self, page_menu_fn)
其中 page_menu_fn(window) -> 当前页的左菜单(QWidget)或 None。
"""
from PySide6.QtCore import QEvent, Qt, QObject


# 自己会消费方向键/回车/选择的交互控件类
_INTERACTIVE = {
    "QListWidget", "QTreeWidget", "QTableWidget", "QComboBox", "QSpinBox",
    "QDoubleSpinBox", "QLineEdit", "QPlainTextEdit", "QTextEdit", "QTextBrowser",
    "QPushButton", "QToolButton", "QTabWidget", "QTabBar", "QMenu",
    "QRadioButton", "QCheckBox", "QScrollBar", "QSlider", "QAbstractButton",
}


def _focus_consumes_keys(widget) -> bool:
    """焦点控件是否自己会消费方向键/回车(是则不导航,防抢键)。"""
    if widget is None:
        return False
    cls = type(widget).__name__
    if cls in _INTERACTIVE:
        return True
    # 子类(如 _ChatInput 是 QPlainTextEdit 子类)→ 用 MRO 判断
    for base in type(widget).__mro__:
        if base.__name__ in _INTERACTIVE:
            return True
    return False


class GlobalNav(QObject):
    """装在窗口上的全局键盘导航(事件过滤器)。"""

    def __init__(self, window, page_menu_fn=None):
        super().__init__(window)
        self.window = window
        self.page_menu_fn = page_menu_fn
        window.installEventFilter(self)

    def _menu(self):
        if callable(self.page_menu_fn):
            try:
                return self.page_menu_fn(self.window)
            except Exception:
                return None
        return None

    def _cycle_tabs(self, direction: int):
        mt = getattr(self.window, "main_tabs", None)
        if mt is None or mt.count() <= 0:
            return
        mt.setCurrentIndex((mt.currentIndex() + direction) % mt.count())

    def _cycle_menu(self, direction: int):
        menu = self._menu()
        if menu is None:
            return
        n = menu.count() if hasattr(menu, "count") else 0
        if n <= 0:
            return
        menu.select(((menu.current() or 0) + direction) % n)

    def _enter_menu(self):
        menu = self._menu()
        if menu is not None:
            try:
                menu._select(menu.current())   # 触发选中(分项切换)
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        # 焦点在自己会消费按键的控件上 → 放行(不抢键)
        if _focus_consumes_keys(self.window.focusWidget()):
            return False
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._cycle_tabs(-1); return True
        if key == Qt.Key.Key_Right:
            self._cycle_tabs(1); return True
        if key == Qt.Key.Key_Up:
            self._cycle_menu(-1); return True
        if key == Qt.Key.Key_Down:
            self._cycle_menu(1); return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._enter_menu(); return True
        return False


def install_global_nav(window, page_menu_fn=None) -> GlobalNav:
    """在窗口上安装全局键盘导航。page_menu_fn(window)->当前页左菜单或 None。"""
    return GlobalNav(window, page_menu_fn)
