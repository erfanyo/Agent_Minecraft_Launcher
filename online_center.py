# -*- coding: utf-8 -*-
"""
联机方案中心(灵感 #2):按场景给玩家推荐联机方案,附官网链接一键打开。
- 现有:按场景分 tab 展示方案卡片 + 跳转官网(不内置任何第三方客户端)。
- 新增:
  A) 「帮我推荐」T/F 向导:一次一题(是/否),按决策树推荐方案,附「打开官网 / 查看教程」;
     若命中 EasyTier 且后端(ler_tools)就绪 → 显示「一键生成房间并分享」(回显 房间钥匙 + 虚拟 IP);
     命中需正版(Essential / Mojang Realms)→ 明确提示「需要正版账号」。
  B) 「教程与资料」tab:整合各方案的人类可读教程(非 CLI 方案为重点),标注「来源:联机方案调研」。
- 一切仍以浏览器/官网 + (后端)下载为准,不内置第三方客户端二进制。
"""
import random
import string

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import t
from ui_style import card_btn_style, muted_color, panel_style


def _open_url(url: str):
    QDesktopServices.openUrl(QUrl(url))

# --------------------------------------------------------------------------
# 现有方案卡片(按场景 tab)
# --------------------------------------------------------------------------
SCHEMES = [
    ("虚拟局域网(朋友联机首选)", [
        ("EasyTier",
         "开源免费,基于 WireGuard 的 P2P 组网,国内网络可用性好;\n朋友们装上后加入同一个网络名,就像在同一 WiFi 下联机。",
         "https://github.com/EasyTier/EasyTier"),
        ("ZeroTier",
         "跨平台虚拟局域网,免费支持 25 台设备;适合天南海北的朋友远程一起玩。",
         "https://www.zerotier.com"),
        ("Radmin VPN",
         "安装即用,创建一个网络后朋友加入,即可像局域网一样联机,延迟低(纯 GUI,无命令行)。",
         "https://www.radmin-vpn.com"),
        ("蒲公英(Oray)",
         "国内真 VPN,跨平台(Win/Mac/Linux/Android/iOS);注册账号建网络,各端装客户端加入即组网,国内网络友好。",
         "https://pgy.oray.com"),
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


# --------------------------------------------------------------------------
# 推荐决策树元数据
# --------------------------------------------------------------------------
SCHEME_META = {
    "EasyTier": {
        "name": "EasyTier",
        "desc": "开源免费的虚拟局域网(LGPL-3.0,基于 WireGuard 的 P2P 组网),免账号、免中心服、跨平台;\n"
                "朋友们装上后用同一「房间名 + 密钥」加入,就像在同一个 WiFi 下联机。",
        "url": "https://github.com/EasyTier/EasyTier",
        "needs_genuine": False, "easytier": True,
    },
    "ZeroTier": {
        "name": "ZeroTier",
        "desc": "跨平台虚拟局域网:网络所有者注册账号建网络,把 16 位网络 ID 发给好友加入(好友无需账号)。",
        "url": "https://www.zerotier.com",
        "needs_genuine": False, "easytier": False,
    },
    "Radmin VPN": {
        "name": "Radmin VPN",
        "desc": "Windows 专用,安装即用;创建网络后朋友加入即可像局域网一样联机,延迟低。",
        "url": "https://www.radmin-vpn.com",
        "needs_genuine": False, "easytier": False,
    },
    "frp": {
        "name": "frp(内网穿透)",
        "desc": "开源端口映射(Apache-2.0);需要一台有公网 IP 的服务器(如 VPS)跑服务端 frps;\n"
                "把家里的服务器穿到公网,朋友用「公网IP:端口」直连。",
        "url": "https://github.com/fatedier/frp",
        "needs_genuine": False, "easytier": False,
    },
    "playit.gg": {
        "name": "playit.gg",
        "desc": "托管端口映射:免公网 IP、免自建服务器,走它家免费中继即可把本地游戏端口开放给全网;需联网。",
        "url": "https://playit.gg",
        "needs_genuine": False, "easytier": False,
    },
    "Essential": {
        "name": "Essential(联机 Mod)",
        "desc": "免费联机 Mod(需 Fabric/Forge),内置好友系统;朋友们都装上后在游戏里直接邀请进世界,\n无需端口映射。",
        "url": "https://essential.gg",
        "needs_genuine": True, "easytier": False,
    },
    "Mojang Realms": {
        "name": "Minecraft Realms(官方)",
        "desc": "Mojang 官方租赁服:无需端口映射、无需公网 IP,适合不想折腾网络的玩家;需订阅。",
        "url": "https://www.minecraft.net/realms",
        "needs_genuine": True, "easytier": False,
    },
}


def recommend(q1: bool, q2: bool, q3: bool, q4: bool) -> str:
    """依据 4 个「是/否」答案推荐方案(参考 `同步-联机方案调研.md` 决策树 §5)。
    q1=需要跨平台; q2=想最省事(不注册账号/不自建服务器); q3=有正版账号; q4=想开服给不在同一网络/全网的朋友。"""
    if q4:  # 想开服给全网/不在同一网络 → 需要把服务器暴露到公网(端口映射/托管)
        if q3:
            return "Mojang Realms"        # 有正版 + 不想自己开服 → 官方托管(需正版+订阅)
        return "playit.gg" if q2 else "frp"   # 省事→托管中继;否则→自建 frp(需公网 VPS)
    if q2:   # 朋友同网络,想最省事、无账号/无中心服 → EasyTier(推荐主路径)
        return "EasyTier"
    if q3:   # 有正版 + 想游戏内联机 → Essential(联机 Mod,需正版)
        return "Essential"
    return "ZeroTier" if q1 else "Radmin VPN"   # 同网、无正版:跨平台→ZeroTier;仅 Windows→Radmin


# --------------------------------------------------------------------------
# 教程与资料(来源:同步-联机方案调研.md)
# --------------------------------------------------------------------------
TUTORIALS = [
    {
        "name": "EasyTier", "cat": "虚拟局域网 · 推荐主路径",
        "text": "开源免费(LGPL-3.0)、去中心化,免账号、免中心服,跨平台(Win/macOS/Linux/手机/OpenWrt)。\n"
                "安装:Windows 可用 `winget install EasyTier.EasyTier`,或直接下载官方 Release 二进制(解压即用,跨平台);\n"
                "后端也可自动下载/安装。\n"
                "方法:朋友们各自安装 easytier-core,用同一「--network-name 房间名 + --network-secret 密钥」加入,即组成同一虚拟网;\n"
                "用 --no-tun 可免管理员、免装虚拟网卡驱动。\n"
                "要点:MC 的「局域网广播/自动发现」默认不会穿过虚拟网,所以可靠做法是——host 把本机虚拟 IP 发给朋友,\n"
                "朋友在 MC 里「直接连接(Direct Connect)」到 host 的虚拟 IP。",
        "url": "https://easytier.cn/",
    },
    {
        "name": "Essential(联机 Mod)", "cat": "联机 Mod · ⚠️需正版",
        "text": "免费的联机 Mod,内置好友系统。\n"
                "⚠️ 必须使用购买了 Minecraft 的微软(正版)账号登录;盗版/离线账号不能用。\n"
                "方法:把 jar 放进 mods(配合 Fabric/Forge),用正版账号登录,在游戏内邀请好友进世界——无需端口映射。",
        "url": "https://essential.gg/wiki/account-manager",
    },
    {
        "name": "Minecraft 官方(LAN / Realms)", "cat": "官方方案 · ⚠️需正版",
        "text": "标准多人:进世界 → 「对局域网开放(Open to LAN)」 → 得到 IP:端口;朋友用「加入服务器」填「主机IP:端口」。\n"
                "注意:若想让不在同一网络的朋友连入,host 需把该端口映射到公网(UPnP / 路由器端口映射 / Natter / frp / playit)。\n"
                "Realms:Mojang 官方托管服(订阅),不需要自设端口、无端口映射,但同样需正版账号。",
        "url": "https://www.minecraft.net/realms",
    },
    {
        "name": "ZeroTier", "cat": "虚拟局域网(需账号)",
        "text": "跨平台虚拟局域网;网络所有者注册账号建网络,拿 16 位网络 ID。\n"
                "好友装客户端后 join 同一网络 ID 即入网(好友无需账号);虚拟 IP 由控制器分配。需管理员装服务/虚拟网卡。\n"
                "MC 里让好友「直接连接」到 host 的虚拟 IP。",
        "url": "https://www.zerotier.com",
    },
    {
        "name": "Tailscale", "cat": "虚拟局域网(需账号)",
        "text": "基于 WireGuard 的私有组网;需注册账号(官方协调服,免费版有设备数限制)。\n"
                "好友也要装客户端并加入同一 tailnet;虚拟 IP 为 100.x 段。\n"
                "可用 --authkey 无人值守自动上线;MC 里「直接连接」到 100.x 虚拟 IP。",
        "url": "https://tailscale.com",
    },
    {
        "name": "frp", "cat": "内网穿透(需公网服务器)",
        "text": "开源端口映射(Apache-2.0);需一台有公网 IP 的服务器(如 VPS)跑服务端 frps。\n"
                "客户端 frpc 用配置文件(frpc.toml)定义 type=tcp 的转发(localPort=MC端口, remotePort=公网端口)。\n"
                "把「VPS公网IP:remotePort」发给朋友;安全建议:只开 MC 游戏端口、设 token。",
        "url": "https://github.com/fatedier/frp",
    },
    {
        "name": "Natter", "cat": "NAT 打洞(免公网IP/免服务器)",
        "text": "开源(NAT 打洞,需家用路由为 full-cone NAT);Python:natter.py -p <端口>。\n"
                "成功后打印公网 tcp://<IP>:<端口> 直接发给朋友;-e <脚本> 可回调自动化。免公网 IP、免自建服务器。",
        "url": "https://github.com/MikeWang000000/Natter",
    },
    {
        "name": "playit.gg / SakuraFrp", "cat": "托管内网穿透(免公网IP)",
        "text": "playit.gg:托管中继,免公网 IP,Agent CLI + secret;免费额度,闭源。\n"
                "SakuraFrp(樱花):国内友好,launcher/frpc + 账号 token;免费额度,闭源。\n"
                "两者都把公网域名/IP:端口发给朋友即可。",
        "url": "https://playit.gg",
    },
    {
        "name": "Radmin VPN", "cat": "虚拟局域网(仅 Windows)",
        "text": "Windows 专用;安装即用,创建一个网络后朋友加入即可像局域网一样联机,延迟低。\n"
                "⚠️ 纯 GUI、无真正 CLI,故**没有「自动安装/配置」按钮**,请按官网/教程手动安装。\n"
                "需账号;不开源。",
        "url": "https://www.radmin-vpn.com",
    },
    {
        "name": "蒲公英 (Oray)", "cat": "虚拟局域网(国内友好)",
        "text": "Oray 旗下国内真 VPN,跨平台(Win/Mac/Linux/Android/iOS),与 EasyTier 一样国内网络友好。\n"
                "方法:注册账号创建网络(选网段/虚拟 IP),各端装客户端后登录并加入同一网络即组网;\n"
                "创网者把网络 ID/成员账号发给朋友加入即可。",
        "url": "https://pgy.oray.com",
    },
]

_TUTORIAL_NOTE = "\n—— 通用要点:所有「虚拟局域网」方案会给 host 和好友各分配一个虚拟 IP;\n" \
                 "MC 的局域网自动发现不会穿过虚拟网,请让好友在 MC 里「直接连接」到 host 的虚拟 IP。\n" \
                 "来源:联机方案调研。"


# --------------------------------------------------------------------------
# EasyTier 后端接入(工程 t24 提供 lan_tools.py;未就绪时优雅降级)
# --------------------------------------------------------------------------
def _lan_tools():
    """按约定接口取 lan_tools 模块;未提供/导入失败返回 None(后端未就绪)。"""
    try:
        import lan_tools
        return lan_tools
    except Exception:
        return None


def _random_room_name() -> str:
    return "AMCL-" + "".join(random.choices(string.ascii_lowercase, k=5))


def _random_secret() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


# --------------------------------------------------------------------------
# A) 「帮我推荐」向导
# --------------------------------------------------------------------------
class RecommendWizard(QWidget):
    """一次只问一题(是/否)的推荐向导,给出推荐方案 + 官网/教程/EasyTier 接入口。"""

    QUESTIONS = [
        ("① 需要跨平台吗?",
         "朋友用的是 Windows / Mac / Linux / 手机等不同系统吗?",
         t("是", "Yes"), t("否", "No")),
        ("② 想最省事、不想注册账号/不想自己开服务器吗?",
         "少折腾:最好不用注册账号、不用自己租服务器/开服?",
         t("是", "Yes"), t("否", "No")),
        ("③ 你有正版 Minecraft 账号吗?",
         "已经购买正版(微软账号)了吗?盗版/离线账号不能用于官方联机、Essential 等。",
         t("是", "Yes"), t("否", "No")),
        ("④ 想开服给「不在同一网络/全网」的朋友吗?",
         "不只是同 WiFi/局域网,想开放给更远、更多朋友?",
         t("是", "Yes"), t("否", "No")),
    ]

    def __init__(self, on_view_tutorial, parent=None):
        super().__init__(parent)
        self.on_view_tutorial = on_view_tutorial   # 回调(scheme_name) → 切换到「教程与资料」tab
        self._answers = []
        self._q_index = 0

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_question_page())   # index 0
        self._stack.addWidget(self._build_result_page())      # index 1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(self._stack)
        self._show_question(0)

    # ---- 问题页 ----
    def _build_question_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self.q_prompt = QLabel()
        self.q_prompt.setWordWrap(True)
        self.q_prompt.setStyleSheet("font-weight: bold; font-size: 15px;")
        self.q_hint = QLabel()
        self.q_hint.setWordWrap(True)
        self.q_hint.setStyleSheet("color: #666666;")
        lay.addWidget(self.q_prompt)
        lay.addWidget(self.q_hint)
        lay.addSpacing(8)
        yes = QPushButton(t("是", "Yes"))
        no = QPushButton(t("否", "No"))
        yes.setMinimumHeight(36)
        no.setMinimumHeight(36)
        yes.clicked.connect(lambda: self._answer(True))
        no.clicked.connect(lambda: self._answer(False))
        row = QHBoxLayout()
        row.addWidget(yes)
        row.addWidget(no)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(8)
        back = QPushButton(t("← 上一步", "← Back"))
        back.clicked.connect(self._back_question)
        lay.addWidget(back)
        lay.addStretch()
        self.q_prompt.setStyleSheet("font-weight: bold; font-size: 15px;")
        return w

    # ---- 结果页 ----
    def _build_result_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        self.res_title = QLabel()
        self.res_title.setWordWrap(True)
        self.res_title.setStyleSheet("font-weight: bold; font-size: 17px;")
        self.res_desc = QLabel()
        self.res_desc.setWordWrap(True)
        self.res_desc.setStyleSheet("color: #444444;")
        self.res_genuine = QLabel()
        self.res_genuine.setWordWrap(True)
        self.res_genuine.setStyleSheet("color: #b23b3b; font-weight: bold;")
        self.res_genuine.setVisible(False)
        lay.addWidget(self.res_title)
        lay.addWidget(self.res_desc)
        lay.addWidget(self.res_genuine)
        lay.addSpacing(10)

        self.res_open = QPushButton(t("打开官网", "Open website"))
        self.res_tut = QPushButton(t("查看教程", "View tutorial"))
        self.res_open.clicked.connect(self._open_recommended_site)
        self.res_tut.clicked.connect(self._view_tutorial)
        row = QHBoxLayout()
        row.addWidget(self.res_open)
        row.addWidget(self.res_tut)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(8)

        # EasyTier 区块
        self.easytier_widget = QWidget()
        et = QVBoxLayout(self.easytier_widget)
        et.setContentsMargins(0, 8, 0, 8)
        self.et_status = QLabel()
        self.et_status.setWordWrap(True)
        self.et_status.setStyleSheet("color: #666666;")
        self.et_gen = QPushButton(t("一键生成房间并分享", "Generate room & share"))
        self.et_gen.clicked.connect(self._easytier_gen)
        et.addWidget(self.et_status)
        et.addWidget(self.et_gen)
        self.et_key = QLineEdit()
        self.et_key.setReadOnly(True)
        self.et_key.setPlaceholderText(t("房间钥匙(name + secret)", "Room key (name + secret)"))
        self.et_vip = QLineEdit()
        self.et_vip.setReadOnly(True)
        self.et_vip.setPlaceholderText(t("虚拟 IP", "Virtual IP"))
        et.addWidget(self.et_key)
        et.addWidget(self.et_vip)
        self.easytier_widget.setVisible(False)
        lay.addWidget(self.easytier_widget)
        lay.addStretch()

        restart = QPushButton(t("重新开始", "Restart"))
        restart.clicked.connect(self._restart)
        lay.addWidget(restart)
        return w

    # ---- 状态机 ----
    def _show_question(self, idx: int):
        self._q_index = idx
        self._stack.setCurrentIndex(0)
        title, hint, _y, _n = self.QUESTIONS[idx]
        self.q_prompt.setText(title)
        self.q_hint.setText(hint)

    def _answer(self, value: bool):
        self._answers.append(value)
        nxt = self._q_index + 1
        if nxt < len(self.QUESTIONS):
            self._show_question(nxt)
        else:
            self._show_result()

    def _back_question(self):
        if self._q_index == 0:
            return
        self._answers.pop()
        self._show_question(self._q_index - 1)

    def _restart(self):
        self._answers = []
        self._show_question(0)

    def _show_result(self):
        q = self._answers
        scheme = recommend(*(q + [False] * (4 - len(q)))) if q else "EasyTier"
        meta = SCHEME_META[scheme]
        self.res_title.setText(t("推荐方案:", "Recommended:") + " " + meta["name"])
        self.res_desc.setText(meta["desc"])
        # 需正版提示
        if meta.get("needs_genuine"):
            self.res_genuine.setText(t("⚠️ 该方案需要正版 Minecraft(微软)账号,盗版/离线账号无法使用。",
                                       "⚠️ This option needs a genuine (Microsoft) Minecraft account; offline/pirated accounts won't work."))
            self.res_genuine.setVisible(True)
        else:
            self.res_genuine.setVisible(False)
        # EasyTier 区块
        if meta.get("easytier"):
            self.easytier_widget.setVisible(True)
            self._refresh_easytier()
        else:
            self.easytier_widget.setVisible(False)
        self._scheme = scheme
        self._stack.setCurrentIndex(1)

    # ---- EasyTier 后端交互 ----
    def _refresh_easytier(self):
        lt = _lan_tools()
        if lt is None:
            self.et_status.setText(t("自动配置未就绪:后端接口暂不可用。请先「打开官网」下载,或手动按教程安装。",
                                     "Auto-setup not ready: backend unavailable. Open the website to download, or follow the tutorial."))
            self.et_gen.setVisible(False)
            return
        self.et_gen.setVisible(True)
        try:
            st = lt.easytier_status()
        except Exception:
            st = {}
        if st.get("installed"):
            self.et_status.setText(t("EasyTier 已就绪,可一键生成房间。", "EasyTier ready — generate a room."))
            self.et_gen.setText(t("一键生成房间并分享", "Generate room & share"))
        else:
            self.et_status.setText(t("自动配置需联网:首次使用请点击下载/安装(或手动按教程装)。",
                                     "Auto-setup needs internet: click to download/install first (or install manually)."))
            self.et_gen.setText(t("下载/安装并生成房间", "Download/install & generate room"))

    def _easytier_gen(self):
        lt = _lan_tools()
        if lt is None:
            self.et_status.setText(t("后端未就绪,请先「打开官网」下载或手动按教程安装。",
                                     "Backend not ready — open the website or install manually."))
            return
        name = _random_room_name()
        secret = _random_secret()
        try:
            res = lt.setup_easytier(name, secret)
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if res and res.get("ok"):
            key = res.get("room_key") or f"{name} / {secret}"
            vip = res.get("virtual_ip") or ""
            self.et_key.setText(key)
            self.et_vip.setText(vip)
            self.et_status.setText(t("✅ 房间已生成;把房间钥匙与虚拟 IP 发给朋友即可。",
                                     "✅ Room created — send the room key & virtual IP to your friends."))
        else:
            err = (res or {}).get("error") or ""
            self.et_status.setText(t("自动配置失败:需联网,首次使用请点击下载;或手动按教程装。" if not err
                                     else f"自动配置失败:{err}",
                                     "Auto-setup failed: needs internet / manual install."))
            self.et_key.setText("")
            self.et_vip.setText("")

    # ---- 结果页按钮 ----
    def _open_recommended_site(self):
        meta = SCHEME_META.get(getattr(self, "_scheme", ""))
        if meta:
            QDesktopServices.openUrl(QUrl(meta["url"]))

    def _view_tutorial(self):
        name = getattr(self, "_scheme", "")
        if self.on_view_tutorial:
            self.on_view_tutorial(name)


# --------------------------------------------------------------------------
# B) 「教程与资料」tab
# --------------------------------------------------------------------------
def build_tutorials_tab() -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    box = QWidget()
    lay = QVBoxLayout(box)
    head = QLabel("—— 教程与资料 ——\n非 CLI 方案(需正版 / 官方)为重点;各方案要点见下。")
    head.setStyleSheet("font-weight: bold; color: #555555;")
    head.setWordWrap(True)
    lay.addWidget(head)
    for tut in TUTORIALS:
        name = QLabel(f"🔹 {tut['name']}  ({tut['cat']})")
        name.setStyleSheet("font-weight: bold; font-size: 14px;")
        name.setWordWrap(True)
        lay.addWidget(name)
        body = QLabel(tut["text"])
        body.setWordWrap(True)
        body.setStyleSheet("color: #666666;")
        lay.addWidget(body)
        open_btn = QPushButton(t("查看官网/教程", "Open official tutorial"))
        open_btn.setFixedWidth(140)
        open_btn.clicked.connect(lambda _c, u=tut["url"]: QDesktopServices.openUrl(QUrl(u)))
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(10)
    note = QLabel(_TUTORIAL_NOTE)
    note.setWordWrap(True)
    note.setStyleSheet("color: #777777;")
    lay.addWidget(note)
    lay.addStretch()
    scroll.setWidget(box)
    return scroll


# --------------------------------------------------------------------------
# 联机方案中心对话框
# --------------------------------------------------------------------------
class OnlineCenter(QWidget):
    """联机方案中心(标签页版,卡片形式):帮我推荐(向导) + 各方案卡片 + 教程与资料"""

    def __init__(self, parent=None):
        super().__init__(parent)

        intro = QLabel(
            "怎么选:\n"
            "· 朋友都在同一个 WiFi / 网络 → 「虚拟局域网」,最稳最省事\n"
            "· 想开服给不在同一网络的朋友 → 「内网穿透」把服务器穿到公网\n"
            "· 不想折腾网络 → 「联机 Mod」或「官方方案」\n"
            "· 拿不准?点「帮我推荐」一路选下去。")
        intro.setWordWrap(True)

        self.tabs = QTabWidget()
        # A) 帮我推荐(放在最前,方便拿不准的玩家)
        self.wizard = RecommendWizard(self._view_tutorial)
        self.tabs.addTab(self.wizard, t("帮我推荐", "Recommend"))

        # 现有方案卡片 tab(card 形式)
        for title, items in SCHEMES:
            self.tabs.addTab(self._build_tab(title, items), title.split("(")[0].strip())

        # B) 教程与资料 tab
        self._tut_index = self.tabs.count()
        self.tabs.addTab(build_tutorials_tab(), t("教程与资料", "Tutorials"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)

    def _view_tutorial(self, scheme_name: str = ""):
        """切到「教程与资料」tab(可选的 scheme 定位简化:切过去即可)。"""
        if hasattr(self, "tabs"):
            self.tabs.setCurrentIndex(self._tut_index)

    def _card(self, name: str, desc: str, url: str) -> QWidget:
        """方案卡片:名称 + 描述 + 打开官网,点击卡片也可打开。"""
        c = QWidget()
        c.setStyleSheet(panel_style())
        lay = QVBoxLayout(c)
        lay.setContentsMargins(12, 10, 12, 10)
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {muted_color()};")
        open_btn = QPushButton(t("打开官网", "Open website"))
        open_btn.setFixedWidth(90)
        open_btn.setStyleSheet(card_btn_style())
        open_btn.clicked.connect(lambda _c, u=url: _open_url(u))
        c.mousePressEvent = lambda _e, u=url: _open_url(u)   # 点击卡片主题也可打开
        r = QHBoxLayout()
        r.addWidget(open_btn)
        r.addStretch()
        lay.addWidget(name_label)
        lay.addWidget(desc_label)
        lay.addLayout(r)
        return c

    def _build_tab(self, title: str, items: list) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(10)
        head = QLabel(f"—— {title} ——")
        head.setStyleSheet("font-weight: bold; color: #555555;")
        v.addWidget(head)
        for name, desc, url in items:
            v.addWidget(self._card(name, desc, url))
        v.addStretch()
        scroll.setWidget(box)
        return scroll


# 兼容旧引用(原为模态对话框)
OnlineCenterDialog = OnlineCenter
