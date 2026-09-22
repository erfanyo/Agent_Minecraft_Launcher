# -*- coding: utf-8 -*-
"""
可复用的全屏内容覆盖层(ContentOverlay):盖在主窗内容区上,显示任意内容 + 左上角返回按钮。

**为什么抽成 API**:下载详情、以及后续任何「点开看详情、返回回原页」的临时视图,都需要
同一套「覆盖层 + 返回」交互。抽成一个通用类,后续新增详情页只需 set_content(你的 widget)。

**用法**:
    ov = ContentOverlay(self._background)          # 父 = 中央区(背景 widget)
    ov.set_title("下载详情")
    ov.set_content(my_content_widget)
    ov.backRequested.connect(lambda: ov.hide_overlay())
    ov.show_overlay()
"""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui_style import card_btn_style, set_style, text_color, current_color


class ContentOverlay(QWidget):
    """内容覆盖层:顶部「← 返回」+ 标题,下面任意内容 widget。默认隐藏。"""

    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentOverlay")
        self._watched_parent = None
        # 半透明面板底(与面板统一:panel_bg),壁纸透出;主内容由调用方在 show 时隐藏
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#contentOverlay {{ background: {current_color('panel_bg')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部栏:返回按钮 + 标题
        top = QWidget()
        top.setObjectName("overlayTop")
        top.setAutoFillBackground(False)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(10)
        self.back_btn = QPushButton("← 返回")
        set_style(self.back_btn, card_btn_style)
        self.back_btn.clicked.connect(self.backRequested.emit)
        self.title_label = QLabel("")
        self.title_label.setStyleSheet(
            f"font-weight: bold; font-size: 15px; color: {text_color()}; background: transparent;")
        tl.addWidget(self.back_btn)
        tl.addWidget(self.title_label)
        tl.addStretch()
        lay.addWidget(top)

        # 内容区(空壳,由 set_content 填入)
        self._content_host = QWidget()
        self._content_host.setAutoFillBackground(False)
        self._content_lay = QVBoxLayout(self._content_host)
        self._content_lay.setContentsMargins(16, 12, 16, 12)
        self._content_lay.setSpacing(8)
        lay.addWidget(self._content_host, 1)

        self.hide()

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_content(self, widget: QWidget) -> None:
        """放入内容 widget(清空之前的内容)。"""
        while self._content_lay.count():
            it = self._content_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        if widget is not None:
            self._content_lay.addWidget(widget)

    def show_overlay(self) -> None:
        """铺满父控件并显示(置顶)。"""
        self.sync_to_parent()
        self.show()
        self.raise_()
        from ui_anim import reveal
        reveal(self._content_host)

    def hide_overlay(self) -> None:
        self.hide()

    # ---- 跟随父控件尺寸 ----
    #
    # 只在 show 时 setGeometry 是不够的:显示期间用户拉大窗口,覆盖层仍是旧尺寸,
    # 内容就缩在左上角一块(实测反馈)。所以装上父控件的事件过滤器,父一改尺寸
    # 就同步——这样「下载详情」和「实例详情」两个覆盖层一起修好。
    def sync_to_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.sync_to_parent()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        parent = self.parentWidget()
        if parent is not None and self._watched_parent is not parent:
            if self._watched_parent is not None:
                self._watched_parent.removeEventFilter(self)
            parent.installEventFilter(self)
            self._watched_parent = parent
        self.sync_to_parent()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._watched_parent is not None:
            self._watched_parent.removeEventFilter(self)
            self._watched_parent = None
        super().hideEvent(event)
