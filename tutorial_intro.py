# -*- coding: utf-8 -*-
"""
新手教程 · 基础知识页(可跳过):在引导式教程正式开始前,先给新手补一遍 MC 常识。

**为什么**:有些完全没接触过 MC 的"新手中的新手",直接进引导教程会懵。这里用
PPT 式的一页(可跳过)讲清楚:MC 有超多版本(网易/国际,都是 基岩 + Java 两套),
我们属于「国际 Java 版」,需要正版账号;并顺带讲版本分类(预览/正式/远古/愚人节+黄金版本)。

**logo**:用 QPainter 现画一个"像素感草方块"(低分辨率,参考国际基岩版 app 图标风格),
不用引入外部图片资源,避免打包/版权问题。
"""
from PySide6.QtCore import QSize, Qt, QRect, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui_style import card_btn_style, hint_style, set_style, text_color, muted_color


def grass_block_icon(size: int = 96) -> QPixmap:
    """画一个像素感草方块 logo(低分辨率放大,参考基岩版 app 图标)。"""
    g = 8      # 内部 8x8 像素网格
    cell = max(2, size // g)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)   # 关抗锯齿 → 硬边像素感
    # 草地(上 2 行,绿色渐变)
    grass_colors = ["#7CBF4A", "#6FB043", "#63A13C", "#57A036", "#6FB043", "#7CBF4A", "#63A13C", "#57A036"]
    for y in range(2):
        for x in range(g):
            c = QColor(grass_colors[(x + y) % len(grass_colors)])
            p.fillRect(QRect(x * cell, y * cell, cell, cell), c)
    # 草地边缘(第 3 行:上绿下渐变)
    for x in range(g):
        c = QColor("#5A9633" if x % 2 == 0 else "#4E822C")
        p.fillRect(QRect(x * cell, 2 * cell, cell, cell), c)
    # 泥土(下 5 行,棕渐变)
    dirt_colors = ["#8A5A35", "#7D4E2E", "#6F4526", "#7A4E2E", "#84552F",
                   "#6F4526", "#7D4E2E", "#8A5A35"]
    for y in range(3, g):
        for x in range(g):
            c = QColor(dirt_colors[(x * 2 + y) % len(dirt_colors)])
            # 随机小块深色石子感
            if (x * 7 + y * 13) % 5 == 0:
                c = QColor("#5E3A20")
            p.fillRect(QRect(x * cell, y * cell, cell, cell), c)
    p.end()
    # 缩放到目标尺寸(已按 cell 缩放,这里直接返回)
    return pm


class TutorialIntroDialog(QDialog):
    """基础知识页:点「开始引导教程」进入正式引导;点「跳过」直接关闭。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("先了解一下 Minecraft")
        self.setMinimumSize(620, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        # ---- logo + 标题 ----
        top = QHBoxLayout()
        logo_lbl = QLabel()
        logo_lbl.setPixmap(grass_block_icon(72))
        logo_lbl.setFixedSize(72, 72)
        title = QLabel("Minecraft 版本太多?先搞清你在玩哪个")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color:{text_color()};")
        title.setWordWrap(True)
        container = QWidget()
        cly = QVBoxLayout(container); cly.setContentsMargins(0, 0, 0, 0); cly.setSpacing(0)
        cly.addStretch()
        cly.addWidget(title)
        cly.addStretch()
        top.addWidget(logo_lbl)
        top.addSpacing(14)
        top.addWidget(container, 1)
        layout.addLayout(top)

        # ---- 正文(绿色块卡片) ----
        body = QLabel(
            "<div style='line-height:1.7;'>"
            "<b>• Minecraft 有超多版本</b> —— 有「网易版」和「国际版」两大阵营,"
            "而且每一版又同时有「基岩版 Bedrock」和「Java 版」两套。<br><br>"
            "<b>• 我们属于国际版 Java 版</b> —— 需要正版账号;"
            "基岩版(手机/主机为主)和网易版那边更偏商业化。"
            "不同阵营/版本不互通,Mod 生态也完全不一样。<br><br>"
            "<b>• 本启动器做的正是「国际 Java 版」的启动器</b> —— "
            "帮你装 Mod、查配方、问 AI、玩各种版本。<br><br>"
            "<b>• 选版本先看类别</b> —— 「正式版」最稳(其中有几个「黄金版本」Mod 生态最好);"
            "「预览版」=公测,可能有 bug;「远古版」=考古,老玩家情怀;"
            "「愚人节版」=官方整活小改(类似整合包),图个乐。<br>"
            "</div>")
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setStyleSheet(
            f"background:{muted_color()};" if False else
            "background:#232e3a; color:#d6dde6; border-radius:12px; padding:16px 18px; font-size:14px;")
        layout.addWidget(body, 1)

        # ---- 按钮:开始引导教程 / 跳过 ----
        btn_row = QHBoxLayout()
        hint = QLabel("看完点「开始引导教程」;不想看直接「跳过」,以后随时可在 设置→界面→重播引导教程。")
        hint.setWordWrap(True)
        hint.setStyleSheet(hint_style())
        btn_row.addWidget(hint, 1)
        skip_btn = QPushButton("跳过")
        start_btn = QPushButton("开始引导教程 ▶")
        set_style(skip_btn, card_btn_style)
        set_style(start_btn, card_btn_style)
        skip_btn.clicked.connect(lambda: self.done(0))
        start_btn.clicked.connect(lambda: self.done(1))
        btn_row.addWidget(skip_btn)
        btn_row.addWidget(start_btn)
        # 按钮行右侧对齐:包成一个 QWidget 再 addWidget
        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_row)
        layout.addWidget(btn_wrap)

    def paintEvent(self, ev):
        super().paintEvent(ev)
