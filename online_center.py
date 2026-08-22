# -*- coding: utf-8 -*-
"""
联机方案中心(灵感 #2):按场景给玩家推荐联机方案,附官网链接一键打开。
纯展示 + 跳转,不内置任何第三方客户端(每种方案的接入成本各不相同,留待后续整合)。
"""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

SCHEMES = [
    ("虚拟局域网(朋友联机首选)", [
        ("EasyTier",
         "开源免费,基于 WireGuard 的 P2P 组网,国内网络可用性好;\n朋友们装上后加入同一个网络名,就像在同一 WiFi 下联机。",
         "https://github.com/EasyTier/EasyTier"),
        ("ZeroTier",
         "跨平台虚拟局域网,免费支持 25 台设备;适合天南海北的朋友远程一起玩。",
         "https://www.zerotier.com"),
        ("Radmin VPN",
         "安装即用,创建一个网络后朋友加入,即可像局域网一样联机,延迟低。",
         "https://www.radmin-vpn.com"),
        ("Tailscale",
         "基于 WireGuard 的私有组网,设备多、管理方便,稳定性好。",
         "https://tailscale.com"),
    ]),
    ("内网穿透(开服但没有公网 IP)", [
        ("SakuraFrp(樱花穿透)",
         "国内最常用的内网穿透,免费节点够用,支持 Minecraft 端口转发;\n适合把家里的服务器穿到公网给全网朋友玩。",
         "https://www.natfrp.com"),
        ("frp",
         "开源自建内网穿透,需要一台有公网 IP 的小服务器做中转。",
         "https://github.com/fatedier/frp"),
    ]),
    ("联机 Mod(不想折腾网络时)", [
        ("Essential",
         "免费联机 Mod,内置好友系统;朋友们都装上后,直接在游戏里邀请进世界,无需端口映射。",
         "https://essential.gg"),
    ]),
    ("官方方案", [
        ("Minecraft Realms",
         "Mojang 官方租赁服,无需端口映射、无需公网 IP,适合不想折腾网络的玩家。",
         "https://www.minecraft.net/realms"),
        ("官方联机渠道",
         "MC26 起 Mojang 提供的官方联机方式,关注启动器内对应的入口。",
         "https://www.minecraft.net"),
    ]),
]


class OnlineCenterDialog(QDialog):
    """联机方案中心:按场景分 tab 展示方案卡片,一键打开官网"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("联机方案中心")
        self.setMinimumSize(580, 460)

        intro = QLabel(
            "怎么选:\n"
            "· 朋友都在同一个 WiFi / 网络 → 「虚拟局域网」,最稳最省事\n"
            "· 想开服给不在同一网络的朋友 → 「内网穿透」把服务器穿到公网\n"
            "· 不想折腾网络 → 「联机 Mod」或「官方方案」\n"
            "点卡片里的「打开官网」看具体步骤。")
        intro.setWordWrap(True)

        self.tabs = QTabWidget()
        for title, items in SCHEMES:
            self.tabs.addTab(self._build_tab(title, items), title.split("(")[0].strip())

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)

    def _build_tab(self, title: str, items: list) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        box = QWidget()
        v = QVBoxLayout(box)

        head = QLabel(f"—— {title} ——")
        head.setStyleSheet("font-weight: bold; color: #555555;")
        v.addWidget(head)

        for name, desc, url in items:
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #666666;")
            open_btn = QPushButton("打开官网")
            open_btn.setFixedWidth(90)
            open_btn.clicked.connect(lambda _c, u=url: QDesktopServices.openUrl(QUrl(u)))

            row = QHBoxLayout()
            row.addWidget(open_btn)
            row.addStretch()

            v.addWidget(name_label)
            v.addWidget(desc_label)
            v.addLayout(row)
            v.addSpacing(8)

        v.addStretch()
        scroll.setWidget(box)
        return scroll
