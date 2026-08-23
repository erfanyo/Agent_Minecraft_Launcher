# -*- coding: utf-8 -*-
"""
AI 助手:停靠在主窗口右侧的对话栏(类似 VS Code 的 AI 侧栏)。

- 接 OpenAI 兼容接口:DeepSeek(默认)/ Ollama 本地 / 自定义
- 对话在后台线程跑,回复经信号回到主线程,不卡界面
- 主窗口通过 ai_context() 提供上下文(选中的实例、启动器设置等)作为系统提示
"""
import base64
import html
import json
import mimetypes
import os
import tempfile
import threading
import time

import requests
from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai_actions import PERMISSIONS, PermissionDenied, permission_instructions, require_workspace_write
from agent_tools import TOOL_FUNCS
from settings import save_settings

# 本地推理(§8.1 拍板模型):接入路由后才启用,懒加载
LOCAL_PROVIDER = "local_builtin"
LOCAL_MODEL_ID = "qwen3.5-0.8b-xlam-q4km"

def chat_completion(messages: list, base_url: str, api_key: str, model: str) -> str:
    """调用 OpenAI 兼容的 /chat/completions,返回回复文本"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(url, headers=headers,
                         json={"model": model, "messages": messages}, timeout=180)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ================= 工具调用(Tool Calling)=================
# 工具 schema:告诉 LLM 有哪些工具、怎么用。与 CLI 命令共用 agent_tools 的实现。
def _tool(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOLS = [
    _tool("list_instances", "列出已安装的实例及其加载器/基础版本", {}, []),
    _tool("search_mods", "搜索 Mod(支持中文名),按游戏版本/加载器过滤",
          {"query": {"type": "string", "description": "搜索词,如 sodium 或 钠"},
           "game_version": {"type": "string", "description": "游戏版本,如 26.2"},
           "loader": {"type": "string", "description": "加载器:fabric/forge"}},
          ["query"]),
    _tool("list_mods", "列出某实例已安装的 Mod 文件",
          {"instance": {"type": "string"}}, ["instance"]),
    _tool("read_instance_log", "读取某实例最近的游戏日志(诊断报错/崩溃用)",
          {"instance": {"type": "string"}}, ["instance"]),
    _tool("read_crash_report", "读取某实例最新的崩溃报告(诊断崩溃用)",
          {"instance": {"type": "string"}}, ["instance"]),
    _tool("get_settings", "查看启动器当前设置(内存/用户名等)", {}, []),
    _tool("install_instance", "下载/创建【新】游戏实例(写操作,需要工作区写权限)。"
          "可创建原版,或带加载器的实例(fabric/forge/neoforge)。"
          "加载器版本留空=自动用最新;可选装 Fabric API / 光影 / 优化 Mod。"
          "注意:这是创建新实例,不是启动已有实例!用户说'建一个/下载一个/创建实例'时用它。"
          "加载器实例会自动下载它依赖的基础原版;整个下载可能要几分钟,"
          "期间请等待,不要重复调用;完成后会返回实例 id",
          {"version": {"type": "string", "description": "游戏版本,如 1.21.1 / 1.20.1 / 26.3-snapshot-8"},
           "loader": {"type": "string", "description": "加载器:fabric/forge/neoforge,留空=原版"},
           "loader_version": {"type": "string", "description": "可选,加载器版本(留空=最新)"},
           "shader": {"type": "boolean", "description": "是否装光影加载器,默认 false"},
           "optimize": {"type": "boolean", "description": "是否装优化 Mod(钠/锂等),默认 false"},
           "fabric_api_version": {"type": "string", "description": "可选,Fabric API 版本(留空不装)"}},
          ["version"]),
    _tool("ask_user", "重要!当用户指令有歧义、缺少关键信息、或需要用户选择时调用:"
          "向用户弹出选择框(可多选,可输入补充),用户的选择会作为结果返回给你。"
          "规则:拿不准用户想要什么时【必须】用这个,不要擅自猜测!例如用户说'帮我推荐mod/该装哪些'"
          "但没说具体装什么时,用这个问用户。用于任务拆分中途确认方向/确认选项,"
          "不要用一次调用问太多问题",
          {"question": {"type": "string", "description": "问题,如 你想装哪些 Mod?"},
           "options": {"type": "array", "items": {"type": "string"},
                       "description": "候选选项,用户可多选(如 [\"钠\",\"锂\",\"玉\",\"JEI\"])"}},
          ["question"]),
    _tool("launch_game", "启动【已存在】的实例游戏(写操作,需要工作区写权限)。"
          "用户说'启动XX/打开游戏/开始玩/进游戏'时用它。注意:只启动,不创建!"
          "实例不存在时改用 install_instance 或先查 list_instances。"
          "这样启动的进程启动器不跟踪日志/退出,关闭游戏窗口即退出",
          {"instance": {"type": "string", "description": "实例 id(用 list_instances 查)"}},
          ["instance"]),
    _tool("install_mod", "给某实例安装单个 Mod(写操作,需要工作区写权限;会先自动备份)。"
          "要一次性装多个 Mod 时,用 install_mods 一次装完,别逐个调用浪费轮数",
          {"slug": {"type": "string"}, "instance": {"type": "string"},
           "version": {"type": "string", "description": "可选,指定版本"}},
          ["slug", "instance"]),
    _tool("install_mods", "批量给某实例安装多个 Mod(一次调用装完所有,省工具轮数)。"
          "支持中文名(如 钠/锂/玉/JEI)或英文 slug。写操作,需要工作区写权限;会自动备份",
          {"slugs": {"type": "array", "items": {"type": "string"},
                     "description": "要装的 Mod 列表,如 [\"钠\",\"锂\",\"玉\"] 或 [\"sodium\",\"lithium\",\"jade\"]"},
           "instance": {"type": "string", "description": "实例 id(用 list_instances 查)"}},
          ["slugs", "instance"]),
    _tool("backup_instance", "备份某实例:存档打包 zip + 模组列表 txt(写操作)",
          {"instance": {"type": "string"}}, ["instance"]),
    _tool("set_setting", "修改启动器设置,如 memory_gb=6(写操作)",
          {"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"]),
    _tool("send_game_command", "向运行中的游戏发送指令(如 /summon zombie 生成僵尸 / weather rain 改雨天)。"
          "自动选通道:优先 bridge-mod 本地指令口(装了 bridge-mod 且进过世界),否则回退 RCON",
          {"instance": {"type": "string", "description": "实例 id(用 list_instances 查)"},
           "command": {"type": "string", "description": "游戏指令,如 summon zombie"}},
          ["instance", "command"]),
    _tool("get_command_guide", "按游戏版本查指令指南(指令要点 + NBT/组件写法 + 核心模板)。"
          "生成指令前先调用,避免版本语法错误",
          {"mc_version": {"type": "string", "description": "游戏版本,如 1.21.1 / 1.12.2"}},
          ["mc_version"]),
    _tool("get_key_bindings", "查询按键绑定:输入按键(空格/左Shift/W/32)返回该键绑了哪些操作"
          "(含 mod 按键,一键多操作全列出);输入功能(前进/攻击/背包/JEI)返回对应按键",
          {"instance": {"type": "string", "description": "实例 id"},
           "query": {"type": "string", "description": "按键或功能词"}},
          ["instance", "query"]),
    _tool("get_recipe_path", "查询物品合成配方,支持中文名(如 终极感应供应器)。"
          "默认返回精简版(只列直接配方一层,省 token);需要完整套娃展开时把 brief 设为 false,"
          "会返回 EMI 风格结果:该物品的全部合成方式(工作台/熔炉/机器等,recipe_index 可切换展开第 N 种)"
          "+ 合成树(每步标注用哪台机器/加工设备)+ 材料总账。"
          "instance 可选,缺省自动用最新导出的配方数据。"
          "注意:若返回开头是『还没有…配方数据』,说明该实例没进过游戏导出配方,"
          "不要反复试其他工具,直接告诉用户:启动对应实例进一次世界即可(bridge-mod 会自动导出)",
          {"item": {"type": "string", "description": "物品名,支持中文/英文/id,如 终极感应供应器 或 mekanism:ultimate_induction_provider"},
           "count": {"type": "integer", "description": "要合成几个,默认 1"},
           "instance": {"type": "string", "description": "实例 id(可选;不传自动用最新数据)"},
           "brief": {"type": "boolean", "description": "true=精简(默认), false=完整配方+合成树+材料总账"},
           "recipe_index": {"type": "integer", "description": "用第几种配方展开(0=第一种,默认 0);完整结果会列出全部配方供选择"}},
          ["item"]),
    _tool("compare_items", "比较物品参数(武器伤害/护甲/护甲韧性/攻速/挖掘等级),返回最强的 N 个。"
          "注意:attribute 必须用中文(武器伤害/护甲/攻速/挖掘等级),不要用英文 damage/armor!",
          {"attribute": {"type": "string", "description": "中文属性名:武器伤害 / 护甲 / 护甲韧性 / 攻速 / 挖掘等级"},
           "top_n": {"type": "integer", "description": "返回前几名,默认 10"}},
          ["attribute"]),
]

# 写操作工具:执行前必须过"工作区可写"权限检查
WRITE_TOOLS = {"install_mod", "install_mods", "install_instance", "launch_game",
               "backup_instance", "set_setting"}


def build_executor(settings: dict):
    """构造工具执行器:LLM 只能"提议",真正执行在这里,权限检查也在这里。
    多余参数会被过滤(模型幻觉传错参数不报错,只调它真需要的)。"""
    import inspect
    import agent_tools

    def executor(name: str, args: dict) -> str:
        # 动态查找:函数名 == 工具名,便于测试打桩与后续扩展
        fn = getattr(agent_tools, name, None)
        if fn is None:
            return f"错误:未知工具 {name}"
        if name in WRITE_TOOLS:
            require_workspace_write(settings)  # 只读权限 → 直接拒绝
        # 灵感 #6:写操作前先自动备份(装 Mod 前防坏档);批量安装只备份一次
        if name in ("install_mod", "install_mods"):
            try:
                backup_note = agent_tools.backup_instance(args.get("instance", ""))
            except Exception as e:
                backup_note = f"(备份失败:{e})"
            result = fn(**args)
            return f"[已自动备份:{backup_note}]\n{result}"
        # 过滤多余参数:只传函数签名里有的(模型经常幻觉多传参数)
        try:
            sig = inspect.signature(fn)
            kwargs = {k: v for k, v in args.items() if k in sig.parameters}
        except (TypeError, ValueError):
            kwargs = args
        return str(fn(**kwargs))

    return executor


def chat_with_tools(messages: list, settings: dict, tools: list,
                    executor, max_rounds: int = 10, on_tool=None,
                    on_user_ask=None, return_messages: bool = False):
    """带工具调用的对话循环:LLM 提议 → 执行 → 结果回传 → 直到完成。

    tools 为 None 时退化为普通对话。
    on_tool(name, args, result) 每执行一个工具就回调一次(供界面显示过程)。
    on_user_ask(question, options) 处理 ask_user 交互工具(主线程弹窗,返回用户选择文本)。
    return_messages=True 时返回 (回复文本, 完整消息历史)——调用方保存历史
    即可实现真正的多轮对话记忆(含工具调用过程)。默认返回回复文本。"""
    url = settings["ai_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.get("ai_api_key"):
        headers["Authorization"] = f"Bearer {settings['ai_api_key']}"

    working = list(messages)
    for _round in range(max_rounds):
        body = {"model": settings["ai_model"], "messages": working}
        if tools:
            body["tools"] = tools
        resp = requests.post(url, headers=headers, json=body, timeout=180)
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        working.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            reply = msg.get("content") or ""
            return (reply, working) if return_messages else reply
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "ask_user":
                # 交互工具:不是静态执行,而是问用户(主线程弹选择框,结果回传)
                if on_user_ask:
                    result = on_user_ask(args.get("question", ""),
                                         args.get("options") or [])
                else:
                    result = "(当前没有用户交互通道,请根据上下文自行判断或说明)"
            else:
                try:
                    result = executor(name, args)
                except PermissionDenied as e:
                    result = f"权限拒绝:{e}"
                except Exception as e:
                    result = f"工具执行失败:{type(e).__name__}: {e}"
            if on_tool:
                on_tool(name, args, result)
            working.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    reply = "(达到最大工具轮数,已停止。可以让我继续,或拆分任务。)"
    return (reply, working) if return_messages else reply


class _Signals(QObject):
    reply = Signal(str)
    error = Signal(str)
    no_tool = Signal()
    self_test = Signal(bool)
    tool_called = Signal(str, dict, str)   # 工具调用过程展示(从 worker 线程 emit,主线程渲染)
    user_ask = Signal(str, list, object, object)   # (问题, 选项, 结果列表引用, 事件) 主线程弹窗
    local_dl_start = Signal()              # 需要开始下载本地模型 → 主线程开下载(带进度弹窗)
    local_dl_progress = Signal(int, int)   # 本地模型下载进度(done, total)(跨线程)
    local_dl_done = Signal(str)            # 本地模型下载完成/失败的消息(跨线程)
    local_status = Signal(str)             # 本地模型状态文字(未下载/下载中/已就绪/推理中)(跨线程)


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def estimate_tokens(text: str) -> int:
    """近似估算 token 数:中文≈1字/token,英文≈4字符/token,再算消息开销。
    只用于上下文占用环的显示,不追求精确(不引入分词库)。"""
    if not text:
        return 4
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return max(1, cjk + other // 4) + 4


# 已知会"看图"(多模态)的模型名关键词。命中才认为支持多模态,否则默认不显示图片功能。
_VISION_MODEL_HINTS = (
    "vision", "vl", "vl-", "4o", "gpt-4", "gpt-4o", "o1", "gemini", "claude-3", "claude-4",
    "llava", "qwen-vl", "qwen2.5-vl", "qwen2-vl", "glm-4v", "internvl", "intern-vl",
    "minicpm-v", "pixtral", "moondream", "cogvlm", "yi-vl", "step-1v", "deepseek-vl",
)


def model_supports_vision(provider: str | None, model: str | None) -> bool | None:
    """粗判某模型是否支持看图(多模态)。

    返回:
    - True  : 支持看图(命中已知视觉模型或 provider 预设 openrouter)→ 显示图片相关按钮;
    - False : 明确不支持看图(内置本地模型、DeepSeek 官方 chat/reasoner)→ 隐藏;
    - None  : 无法判断(本地/自定义/未知模型)→ 交由用户手动开关 ai_multimodal 决定。

    依据:先看 provider 预设(local_builtin 不支持 / openrouter 默认支持),再看模型名关键词
    (含 vision/vl 等,或 gpt-4o/gemini/claude 等已知视觉系列)。
    """
    name = (model or "").strip().lower()
    if provider == "local_builtin":
        return False          # 内置本地模型(目前 xLAM/Qwen3.5)不支持图片
    if provider == "openrouter":
        return True           # OpenRouter 聚合多模型,默认按支持看图处理(用户可取消勾选覆盖)
    if provider == "deepseek" and "vl" not in name and "vision" not in name:
        return False          # DeepSeek 官方 chat/reasoner 不支持图片
    if not name:
        return None
    for hint in _VISION_MODEL_HINTS:
        if hint in name:
            return True
    return None               # 未知模型:保守,交给手动开关


class ContextRing(QWidget):
    """小圆环:显示上下文占用比例(绿→黄→红),悬停显示具体数字。
    样式与下载指示器(DownloadIndicator)一致,只是更小、中心显示百分比。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._used = 0
        self._limit = 1
        self._color = "#4CAF50"
        self.setFixedSize(30, 30)
        self.setToolTip("上下文占用")
        self.setStyleSheet("background: transparent;")

    def set_usage(self, used: int, limit: int):
        self._used = max(used, 0)
        self._limit = max(limit, 1)
        ratio = min(1.0, self._used / self._limit)
        if ratio < 0.6:
            self._color = "#4CAF50"
        elif ratio < 0.85:
            self._color = "#F59E0B"
        else:
            self._color = "#E53935"
        self.setToolTip(f"上下文: 已用 {self._used:,} / {self._limit:,} tokens ({ratio * 100:.0f}%)")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        # 背景环
        p.setPen(QPen(QColor(190, 190, 190, 120), 3))
        p.drawEllipse(rect)
        # 占用弧(从 12 点方向顺时针)
        ratio = min(1.0, self._used / self._limit)
        if ratio > 0:
            span = int(360 * ratio)
            pen = QPen(QColor(self._color), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -span * 16)
        # 中心百分比
        p.setPen(QColor(self._color))
        font = p.font()
        font.setPixelSize(7)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{ratio * 100:.0f}%")
        p.end()


def collect_screenshots(game_dir: str, limit: int = 30) -> list:
    """收集最近的游戏截图(按修改时间新→旧,最多 limit 张)。
    截图位置:未版本隔离 → <game_dir>/screenshots;隔离 → <game_dir>/versions/<id>/screenshots。"""
    dirs = [os.path.join(game_dir, "screenshots")]
    versions_dir = os.path.join(game_dir, "versions")
    if os.path.isdir(versions_dir):
        try:
            for name in os.listdir(versions_dir):
                dirs.append(os.path.join(versions_dir, name, "screenshots"))
        except OSError:
            pass
    rows = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in files:
            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                p = os.path.join(d, f)
                try:
                    rows.append((os.path.getmtime(p), p))
                except OSError:
                    continue
    rows.sort(reverse=True)
    return [p for _m, p in rows[:limit]]


class RecentScreenshotsDialog(QDialog):
    """微信式"最近照片":列出 .minecraft 里的最近游戏截图,双击或选中点"添加"进 AI 输入。"""

    def __init__(self, game_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("最近截图")
        self.setMinimumSize(560, 400)
        self.picked = []   # 选中的图片路径

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(120, 68))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setWordWrap(True)
        shots = collect_screenshots(game_dir, limit=30)
        if not shots:
            hint = QLabel("还没有截图。游戏里按 F2 截图后会自动存到 .minecraft 里(启动器会自动找到)。")
            hint.setWordWrap(True)
            hint.setStyleSheet("color:#888888;")
        else:
            hint = QLabel(f"共找到最近 {len(shots)} 张截图:双击添加,或选中多张点[添加]")
            hint.setStyleSheet("color:#888888;")
            for p in shots:
                name = os.path.basename(p)
                when = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
                item = QListWidgetItem(QIcon(p), f"{name}\n{when}")
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                self.list.addItem(item)

        add_btn = QPushButton("添加选中")
        add_btn.setEnabled(bool(shots))
        add_btn.clicked.connect(self._add_selected)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(hint, 1)
        row.addStretch()
        row.addWidget(add_btn)
        row.addWidget(cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(row)

        self.list.itemDoubleClicked.connect(lambda _it: self._add_selected())

    def _add_selected(self):
        self.picked = [it.data(Qt.ItemDataRole.UserRole)
                       for it in self.list.selectedItems()
                       if it.data(Qt.ItemDataRole.UserRole)]
        if self.picked:
            self.accept()


# 云端服务商(下拉选项:标签, 值)
_CLOUD_PROVIDERS = [
    ("DeepSeek(推荐 · 便宜好用)", "deepseek"),
    ("OpenRouter(一家账号用多家,部分模型会看图)", "openrouter"),
    ("硅基流动(国内速度快)", "siliconflow"),
    ("智谱 GLM(国内)", "zhipu"),
    ("通义千问(国内)", "dashscope"),
    ("自定义(自己填接口)", "custom"),
]
# 本地模型类型(下拉:标签, 值)
_LOCAL_MODES = [
    ("内置本地模型(离线,无密钥,需下载)", "builtin"),
    ("Ollama(本地服务,免费离线)", "ollama"),
    ("LM Studio(本地服务,免费离线)", "lmstudio"),
]


class AISettingsForm(QWidget):
    """AI 模型设置(拆分云端 / 本地两大块)。

    - 顶部「当前使用」:云端模型 / 本地模型(单选)—— 决定 AI 对话走哪边。
    - 云端块:服务商(DeepSeek/OpenRouter/硅基流动/智谱/通义/自定义)+ 接口地址 + API 密钥 + 模型。
    - 本地块:本地类型(内置 / Ollama / LM Studio)+
      内置:模型下载状态 + 自动下载;Ollama/LM Studio:服务地址 + 模型名。
    - 通用:文件权限、上下文窗口、图片输入(按模型自动)、游戏内 AI 通道。

    保存时据当前来源推导「生效」的 ai_provider / ai_base_url / ai_api_key / ai_model,
    后端(chat/task_router/local 路由)读到的是统一的一套,零改动。
    """

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._build_ui()
        self._sync_from_settings()
        self._apply_source_visibility()

    def _build_ui(self):
        # ---------- 当前使用(来源单选) ----------
        self.source_cloud = QRadioButton("☁ 云端模型")
        self.source_local = QRadioButton("🖥 本地模型")
        self.source_cloud.setToolTip("走云端 API(DeepSeek / OpenRouter / 硅基流动 / 智谱 / 通义 / 自定义)")
        self.source_local.setToolTip("本地推理(内置小模型 / Ollama / LM Studio),离线可用")
        self.source_cloud.toggled.connect(self._apply_source_visibility)

        # ---------- 云端块 ----------
        self.cloud_provider = QComboBox()
        for label, value in _CLOUD_PROVIDERS:
            self.cloud_provider.addItem(label, value)
        self.cloud_base_url = QLineEdit()
        self.cloud_base_url.setPlaceholderText("如 https://api.deepseek.com/v1")
        self.cloud_api_key = QLineEdit()
        self.cloud_api_key.setPlaceholderText("在对应平台注册获取;本地服务留空")
        self.cloud_model = QLineEdit()
        self.cloud_model.setPlaceholderText("如 deepseek-chat / glm-4-flash")
        cloud_box = QGroupBox("云端模型")
        cl = QFormLayout(cloud_box)
        cl.addRow("服务商:", self.cloud_provider)
        cl.addRow("接口地址:", self.cloud_base_url)
        cl.addRow("API 密钥:", self.cloud_api_key)
        cl.addRow("模型:", self.cloud_model)

        # ---------- 本地块 ----------
        self.local_mode = QComboBox()
        for label, value in _LOCAL_MODES:
            self.local_mode.addItem(label, value)
        # 内置模型专属:下载状态 + 自动下载
        self.local_builtin_row = QWidget()
        b_row = QHBoxLayout(self.local_builtin_row)
        b_row.setContentsMargins(0, 0, 0, 0)
        self.local_status = QLabel("")
        self.local_auto_dl = QCheckBox("首次用到且未下载时自动下载")
        self.local_auto_dl.setChecked(True)
        b_row.addWidget(self.local_status, 1)
        b_row.addWidget(self.local_auto_dl)
        # Ollama / LM Studio 专属:服务地址 + 模型名
        self.local_server_row = QWidget()
        s_form = QFormLayout(self.local_server_row)
        s_form.setContentsMargins(0, 0, 0, 0)
        self.local_endpoint = QLineEdit()
        self.local_endpoint.setPlaceholderText("如 http://localhost:11434/v1")
        self.local_model = QLineEdit()
        self.local_model.setPlaceholderText("本机加载的模型名,如 qwen2.5:7b")
        s_form.addRow("服务地址:", self.local_endpoint)
        s_form.addRow("模型名:", self.local_model)
        local_box = QGroupBox("本地模型")
        ll = QVBoxLayout(local_box)
        ll.addWidget(QLabel("本地类型:"))
        ll.addWidget(self.local_mode)
        ll.addWidget(self.local_builtin_row)
        ll.addWidget(self.local_server_row)

        # ---------- 通用 ----------
        self.permission = QComboBox()
        for label, value in PERMISSIONS:
            self.permission.addItem(label, value)
        self.context_window = QSpinBox()
        self.context_window.setRange(1000, 1000000)
        self.context_window.setSingleStep(1024)
        self.context_window.setSuffix(" tokens")
        self.context_window.setToolTip("模型上下文窗口上限,用于对话框里的占用圆环显示")
        self.vision_check = QCheckBox("允许给 AI 发图片(需要所选模型本身支持看图)")
        self.vision_check.setToolTip(
            "图片功能不是想开就开:要看你选的模型本身会不会\"看图\"(多模态)。\n"
            "不确定的话保持关闭最稳妥;勾了但模型不支持,发图片时会报错。")
        self.ai_in_game = QComboBox()
        self.ai_in_game.addItem("关闭(游戏内不用 AI,推荐)", "off")
        self.ai_in_game.addItem("云端(游戏内用云端 AI)", "cloud")
        self.ai_in_game.addItem("本地(游戏内用内置本地模型)", "local")
        self.ai_in_game.setToolTip(
            "游戏运行时是否保留本地模型:\n"
            "· off/cloud → 游戏启动时卸载本地模型,省内存给游戏;\n"
            "· local → 游戏启动时保持本地模型加载(游戏内 AI 通道,规划中)。")

        common = QGroupBox("通用")
        cf = QFormLayout(common)
        cf.addRow("文件权限:", self.permission)
        cf.addRow("上下文窗口:", self.context_window)
        cf.addRow("图片输入:", self.vision_check)
        cf.addRow("游戏内 AI:", self.ai_in_game)

        # ---------- 布局 ----------
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_cloud)
        source_row.addWidget(self.source_local)
        source_row.addStretch()
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(QLabel("当前使用:"))
        layout.addLayout(source_row)
        layout.addWidget(cloud_box)
        layout.addWidget(local_box)
        layout.addWidget(common)

        # 联动
        self.cloud_provider.currentIndexChanged.connect(self._fill_cloud_defaults)
        self.cloud_provider.currentIndexChanged.connect(self._auto_vision)
        self.cloud_model.textChanged.connect(self._auto_vision)
        self.local_mode.currentIndexChanged.connect(self._on_local_mode_changed)
        self.local_mode.currentIndexChanged.connect(self._auto_vision)
        self.local_model.textChanged.connect(self._auto_vision)

        self.cloud_box = cloud_box
        self.local_box = local_box

    def _sync_from_settings(self):
        """从 settings 载入(组合/文本设置时屏蔽信号,避免 _fill_* 覆盖用户已存值)。"""
        s = self._settings
        self.blockSignals(True)
        source = s.get("ai_source", "cloud")
        self.source_cloud.setChecked(source != "local")
        self.source_local.setChecked(source == "local")
        # 云端
        self.cloud_provider.setCurrentIndex(
            self.cloud_provider.findData(s.get("ai_cloud_provider", "deepseek")) if self.cloud_provider.findData(
                s.get("ai_cloud_provider", "deepseek")) >= 0 else 0)
        self.cloud_base_url.setText(s.get("ai_cloud_base_url", ""))
        self.cloud_api_key.setText(s.get("ai_cloud_api_key", ""))
        self.cloud_model.setText(s.get("ai_cloud_model", ""))
        # 本地
        self.local_mode.setCurrentIndex(
            self.local_mode.findData(s.get("ai_local_mode", "builtin")) if self.local_mode.findData(
                s.get("ai_local_mode", "builtin")) >= 0 else 0)
        self.local_endpoint.setText(s.get("ai_local_endpoint", ""))
        self.local_model.setText(s.get("ai_local_model", ""))
        self.local_auto_dl.setChecked(bool(s.get("ai_local_auto_download", True)))
        # 通用
        cur = s.get("ai_permission", "readonly")
        idx = self.permission.findData(cur)
        self.permission.setCurrentIndex(idx if idx >= 0 else 0)
        self.context_window.setValue(int(s.get("context_window", 65536) or 65536))
        self.vision_check.setChecked(bool(s.get("ai_multimodal", False)))
        ig = s.get("ai_in_game", "off")
        idx = self.ai_in_game.findData(ig)
        self.ai_in_game.setCurrentIndex(idx if idx >= 0 else 0)
        self.blockSignals(False)
        self._toggle_local_visibility()   # 仅切换显隐,不改用户已存值
        self._refresh_local_status()

    # ---- 来源/本地类型切换 ----
    def _apply_source_visibility(self, *_):
        is_cloud = self.source_cloud.isChecked()
        self.cloud_box.setVisible(is_cloud)
        self.local_box.setVisible(not is_cloud)

    def _toggle_local_visibility(self, *_):
        """仅按本地类型切换子区显隐 + 内置模型只读,不改用户已存值。"""
        mode = self.local_mode.currentData()
        builtin = (mode == "builtin")
        self.local_builtin_row.setVisible(builtin)
        self.local_server_row.setVisible(not builtin)
        self.local_model.setReadOnly(builtin)
        if builtin:
            self.local_model.setText(LOCAL_MODEL_ID)
        self._refresh_local_status()

    def _on_local_mode_changed(self, *_):
        """用户切换本地类型:先切显隐,再补默认端点/模型名(仅空格/内置默认时)。"""
        self._toggle_local_visibility()
        mode = self.local_mode.currentData()
        if mode == "ollama":
            if not self.local_endpoint.text().strip():
                self.local_endpoint.setText("http://localhost:11434/v1")
            if not self.local_model.text().strip() or self.local_model.text() == LOCAL_MODEL_ID:
                self.local_model.setText("qwen2.5:7b")
        elif mode == "lmstudio":
            if not self.local_endpoint.text().strip():
                self.local_endpoint.setText("http://localhost:1234/v1")
            self.local_model.clear()
            self.local_model.setPlaceholderText("输入你已在 LM Studio 加载的模型名")

    def _fill_cloud_defaults(self):
        idx = self.cloud_provider.currentData()
        if idx == "deepseek":
            self.cloud_base_url.setText("https://api.deepseek.com/v1")
            self.cloud_model.setText("deepseek-chat")
        elif idx == "openrouter":
            self.cloud_base_url.setText("https://openrouter.ai/api/v1")
            self.cloud_model.setText("deepseek/deepseek-chat-v3-0324:free")
        elif idx == "siliconflow":
            self.cloud_base_url.setText("https://api.siliconflow.cn/v1")
            self.cloud_model.setText("Qwen/Qwen2.5-7B-Instruct")
        elif idx == "zhipu":
            self.cloud_base_url.setText("https://open.bigmodel.cn/api/paas/v4")
            self.cloud_model.setText("glm-4-flash")
        elif idx == "dashscope":
            self.cloud_base_url.setText("https://dashscope.aliyuncs.com/compatible-mode/v1")
            self.cloud_model.setText("qwen-plus")
        # custom:保留用户输入

    def _refresh_local_status(self):
        """刷新内置本地模型的下载状态文字。"""
        if not hasattr(self, "local_status"):
            return
        try:
            import model_registry
            ready = model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            ready = False
        self.local_status.setText("内置模型:" + ("✅ 已下载" if ready else "未下载(约500MB,首次用自动下载)"))

    def _auto_vision(self):
        """切服务商/模型时,按所选(生效的)模型是否能看图自动设定「图片输入」开关。"""
        if self.source_cloud.isChecked():
            prov, model = self.cloud_provider.currentData(), self.cloud_model.text().strip()
        else:
            prov = "local_builtin" if self.local_mode.currentData() == "builtin" else self.local_mode.currentData()
            model = LOCAL_MODEL_ID if prov == "local_builtin" else self.local_model.text().strip()
        vis = model_supports_vision(prov, model)
        if vis is True:
            self.vision_check.setChecked(True)
            self.vision_check.setToolTip("该模型看起来支持看图(多模态),已自动开启。")
        elif vis is False:
            self.vision_check.setChecked(False)
            self.vision_check.setToolTip("该模型不支持看图(多模态),图片功能已自动关闭。")

    def values(self) -> dict:
        """收集表单内容为设置字段,并据当前来源推导「生效」的一组 ai_provider/... 给后端。"""
        if self.source_cloud.isChecked():
            source = "cloud"
            provider = self.cloud_provider.currentData()
            base_url = self.cloud_base_url.text().strip()
            api_key = self.cloud_api_key.text().strip()
            model = self.cloud_model.text().strip()
        else:
            source = "local"
            mode = self.local_mode.currentData()
            provider = "local_builtin" if mode == "builtin" else mode
            base_url = "" if mode == "builtin" else self.local_endpoint.text().strip()
            api_key = ""
            model = LOCAL_MODEL_ID if mode == "builtin" else self.local_model.text().strip()
        return {
            "ai_source": source,
            # 云端组
            "ai_cloud_provider": self.cloud_provider.currentData(),
            "ai_cloud_base_url": self.cloud_base_url.text().strip(),
            "ai_cloud_api_key": self.cloud_api_key.text().strip(),
            "ai_cloud_model": self.cloud_model.text().strip(),
            # 本地组
            "ai_local_mode": self.local_mode.currentData(),
            "ai_local_endpoint": self.local_endpoint.text().strip(),
            "ai_local_model": (LOCAL_MODEL_ID if self.local_mode.currentData() == "builtin"
                               else self.local_model.text().strip()),
            "ai_local_auto_download": self.local_auto_dl.isChecked(),
            # 生效(后端读取)
            "ai_provider": provider,
            "ai_base_url": base_url,
            "ai_api_key": api_key,
            "ai_model": model,
            # 通用
            "ai_permission": self.permission.currentData(),
            "context_window": self.context_window.value(),
            "ai_multimodal": self.vision_check.isChecked(),
            "ai_in_game": self.ai_in_game.currentData(),
        }


class AISettingsDialog(QDialog):
    """AI 服务设置:服务商 / 接口地址 / 密钥 / 模型"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 助手设置")
        self.setMinimumWidth(380)
        self.settings = dict(settings)

        self.form = AISettingsForm(self.settings, self)
        # 兼容旧用法:直接访问 dlg.provider / dlg.base_url / dlg.permission 等
        # (现在分云端/本地两组,旧别名指向云端服务商那组)
        self.provider = self.form.cloud_provider
        self.base_url = self.form.cloud_base_url
        self.api_key = self.form.cloud_api_key
        self.model = self.form.cloud_model
        self.permission = self.form.permission
        self.context_window = self.form.context_window

        hint = QLabel(
            "怎么选:\n"
            "· 云端(DeepSeek / OpenRouter / 硅基流动 / 智谱 / 通义):去官网注册拿密钥,填右上(DeepSeek 最便宜);\n"
            "· 本地(内置本地模型 / Ollama / LM Studio):离线可用;内置模型约 500MB 首次用自动下载;\n"
            "· 发图片:和用哪家无关,取决于所选模型本身会不会\"看图\"(内置本地模型不支持,自动关闭);\n"
            "文件权限:只读 = AI 只能看文件;工作区可写 = AI 只能在启动器目录里改文件。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def accept(self):
        self.settings.update(self.form.values())
        super().accept()


class AskUserDialog(QDialog):
    """AI 拿不准用户意图时弹出:多选选项 + 可输入补充(保留输入框)。
    返回:用户勾选的选项 + 手动输入的补充。"""

    def __init__(self, question: str, options: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 需要你确认")
        self.setMinimumWidth(420)
        self.question_label = QLabel(question or "你想要哪个?")
        self.question_label.setWordWrap(True)
        self.checks = [QCheckBox(o) for o in (options or [])]
        self.input = QLineEdit()
        self.input.setPlaceholderText("选项不够?直接输入补充(可多选后再补充)...")
        self.input.setToolTip("多选下面的选项,或在输入框补充说明;都会发给 AI")

        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.question_label)
        for c in self.checks:
            layout.addWidget(c)
        layout.addSpacing(6)
        layout.addWidget(self.input)
        layout.addLayout(row)

    def selected(self) -> list:
        """收集:勾选项 + 输入补充(非空)"""
        picked = [c.text() for c in self.checks if c.isChecked()]
        extra = self.input.text().strip()
        if extra:
            picked.append(extra)
        return picked


class SendWithRing(QWidget):
    """发送按钮 + 外圈上下文占用环(表示方式与下载指示器一致):
    发送按钮缩小居中,外圈环形显示上下文已用比例,绿→黄→红。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._used = 0
        self._limit = 1
        self._color = "#4CAF50"
        self.setFixedSize(40, 40)
        self.setToolTip("发送(Enter) | 上下文: 0%")
        self.setStyleSheet("background: transparent;")
        self.btn = QPushButton("↑", self)
        self.btn.setFixedSize(26, 26)
        self.btn.move(7, 7)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            "QPushButton{border-radius:13px; background:#3E7CB1; color:white;"
            " font-size:15px; font-weight:bold; border:none;}"
            "QPushButton:hover{background:#5B8DEF;}"
            "QPushButton:pressed{background:#2E5A85;}")
        self.btn.clicked.connect(self.clicked.emit)

    def click(self):
        self.btn.click()

    def set_usage(self, used: int, limit: int):
        self._used = max(used, 0)
        self._limit = max(limit, 1)
        ratio = min(1.0, self._used / self._limit)
        if ratio < 0.6:
            self._color = "#4CAF50"
        elif ratio < 0.85:
            self._color = "#F59E0B"
        else:
            self._color = "#E53935"
        self.setToolTip(f"发送(Enter) | 上下文: 已用 {self._used:,} / "
                        f"{self._limit:,} tokens ({ratio * 100:.0f}%)")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        # 背景环
        p.setPen(QPen(QColor(190, 190, 190, 120), 2))
        p.drawEllipse(rect)
        # 上下文占用弧
        ratio = min(1.0, self._used / self._limit)
        if ratio > 0:
            span = max(int(360 * ratio), 2)
            pen = QPen(QColor(self._color), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -span * 16)
        p.end()


class _ChatInput(QPlainTextEdit):
    """AI 输入框:多行 + 自带滚动条,Enter 发送、Shift+Enter 换行;
    右下角内置圆形 ↑ 发送按钮 + 🛠 工具测试按钮 + 📷 图片按钮(挨着发送)。
    支持粘贴图片(触发 imagePasted)。兼容旧 QLineEdit 接口(setText/text),方便测试与外部代码。"""
    returnPressed = Signal()
    sendClicked = Signal()
    testClicked = Signal()
    imageClicked = Signal()
    recentClicked = Signal()
    imagePasted = Signal(QImage)   # 从剪贴板粘贴了图片

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(56)
        self.setMaximumHeight(160)
        # 发送按钮缩小居中,外圈环绕上下文占用环(与下载指示器同款表示)
        self.send_btn = SendWithRing(self)
        self.send_btn.setToolTip("发送(Enter)")
        self.send_btn.clicked.connect(self.sendClicked.emit)
        # 工具测试:挨着发送按钮
        self.test_btn = QPushButton("🛠", self)
        self.test_btn.setFixedSize(30, 30)
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.setToolTip("自测工具调用:让模型调用一个工具,看它支不支持")
        self.test_btn.setStyleSheet(
            "QPushButton{border-radius:15px; background:rgba(128,128,128,90);"
            " font-size:14px; border:none;}"
            "QPushButton:hover{background:rgba(128,128,128,160);}")
        self.test_btn.clicked.connect(self.testClicked.emit)
        # 图片:挨着 🛠(最左边),也支持 Ctrl+V 粘贴
        self.img_btn = QPushButton("📷", self)
        self.img_btn.setFixedSize(30, 30)
        self.img_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.img_btn.setToolTip("添加图片(也支持 Ctrl+V 粘贴截图)")
        self.img_btn.setStyleSheet(
            "QPushButton{border-radius:15px; background:rgba(128,128,128,90);"
            " font-size:14px; border:none;}"
            "QPushButton:hover{background:rgba(128,128,128,160);}")
        self.img_btn.clicked.connect(self.imageClicked.emit)
        # 最近照片:微信式,列出 .minecraft 里的游戏截图(再左边)
        self.recent_btn = QPushButton("🖼", self)
        self.recent_btn.setFixedSize(30, 30)
        self.recent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_btn.setToolTip("最近截图:从 .minecraft 里选游戏内 F2 截图")
        self.recent_btn.setStyleSheet(
            "QPushButton{border-radius:15px; background:rgba(128,128,128,90);"
            " font-size:14px; border:none;}"
            "QPushButton:hover{background:rgba(128,128,128,160);}")
        self.recent_btn.clicked.connect(self.recentClicked.emit)
        # 右下角按钮顺序(从右到左):发送环 → 🛠 → 📷 → 🖼
        # 📷/🖼 是图片相关按钮,模型不支持多模态时隐藏(见 set_vision_enabled)
        self._corner_btns = [self.send_btn, self.test_btn, self.img_btn, self.recent_btn]
        self._vision = True

    def set_vision_enabled(self, on: bool):
        """按模型是否支持多模态显示/隐藏图片相关按钮(📷 添加图片、🖼 最近截图)"""
        self._vision = bool(on)
        self.img_btn.setVisible(self._vision)
        self.recent_btn.setVisible(self._vision)
        self.setPlaceholderText(
            "问 AI 任何问题…(Enter 发送, Shift+Enter 换行;Ctrl+V 可粘贴图片)" if self._vision
            else "问 AI 任何问题…(Enter 发送, Shift+Enter 换行)")
        self._layout_corner_buttons()   # 重新摆放右下角按钮

    def vision_enabled(self) -> bool:
        return self._vision

    def _layout_corner_buttons(self):
        """把右下角圆形按钮从右到左依次摆放,只排可见的按钮"""
        m = 6
        x = self.width() - m
        for b in reversed(self._corner_btns):
            if not b.isVisible():
                continue
            x -= b.width() + m
            b.move(x, self.height() - b.height() - m)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_corner_buttons()

    def canInsertFromMimeData(self, source):
        return source.hasImage() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasImage():
            self.imagePasted.emit(source.imageData())
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, e):
        if (e.key() == Qt.Key.Key_Return or e.key() == Qt.Key.Key_Enter) \
                and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.returnPressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def setText(self, t: str):
        self.setPlainText(t)

    def text(self) -> str:
        return self.toPlainText()


class AIChatDock(QDockWidget):
    """右侧停靠的 AI 对话栏"""

    def __init__(self, parent, settings: dict):
        super().__init__("AI 助手", parent)
        self.main = parent
        self.settings = settings
        self.signals = _Signals()
        self.signals.reply.connect(self._on_reply)
        self.signals.error.connect(self._on_error)
        self.signals.no_tool.connect(self._on_no_tool)
        self.signals.self_test.connect(self._on_self_test)
        # 工具调用过程展示:worker 线程只 emit 信号,渲染回到主线程(跨线程操作 UI 会崩)
        self.signals.tool_called.connect(self._show_tool)
        # ask_user 交互:worker 线程请求 → 主线程弹窗 → 结果回传
        self.signals.user_ask.connect(self._on_user_ask_ui)
        # 本地模型下载(跨线程发信号,主线程更新进度弹窗,避免跨线程碰 UI)
        self.signals.local_dl_start.connect(self._start_local_download)
        self.signals.local_dl_progress.connect(self._on_local_dl_progress)
        self.signals.local_dl_done.connect(self._on_local_dl_done)
        self.signals.local_status.connect(self._on_local_status)

        self.history = QTextBrowser()
        self.history.anchorClicked.connect(self._on_anchor)  # 自己处理链接(展开工具日志/开外部链接)
        self.history.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }")
        self.input = _ChatInput()
        self.input.setPlaceholderText("问 AI 任何问题…(Enter 发送, Shift+Enter 换行;Ctrl+V 可粘贴图片)")
        self.input.returnPressed.connect(self.send)
        self.input.sendClicked.connect(self.send)
        self.input.testClicked.connect(self.self_test_tools)   # 🛠 已移进输入框,挨着发送
        self.input.imageClicked.connect(self._pick_images)
        self.input.imagePasted.connect(self._add_image_data)
        self.input.recentClicked.connect(self._pick_recent_screenshots)
        # 浮动/停靠使用 QDockWidget 标题栏右上角自带的浮动按钮(与系统行为整合)

        # 顶部:标题 + 当前模型/多模态徽标 + 技能管理入口
        title = QLabel("AI 助手")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.model_label = QLabel("")
        self.model_label.setToolTip("当前使用的模型,以及是否支持看图(多模态)")
        skills_btn = QPushButton("技能管理…")
        skills_btn.setToolTip("管理游戏运行时辅助技能(指令指南/崩溃守护等)")
        skills_btn.clicked.connect(self.open_skill_manager)
        skills_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #8b96a8; border: 1px solid #3a4150;"
            " border-radius: 6px; padding: 3px 8px; }"
            "QPushButton:hover { color: #ffffff; border-color: #5B8DEF; }")
        top_row = QHBoxLayout()
        top_row.setContentsMargins(2, 0, 2, 0)
        top_row.addWidget(title)
        top_row.addSpacing(6)
        top_row.addWidget(self.model_label)
        # 本地模型状态(未下载/下载中/已就绪/推理中),仅本地 provider 时显示
        self.local_status_label = QLabel("")
        self.local_status_label.setVisible(False)
        top_row.addSpacing(6)
        top_row.addWidget(self.local_status_label)
        top_row.addStretch()
        top_row.addWidget(skills_btn)

        # 文件权限:放在输入框附近,一眼可见、一键切换(不藏进二级菜单)
        perm_btn = QPushButton("切换")
        perm_btn.setFixedWidth(44)
        perm_btn.setToolTip("在 只读 / 工作区可写 之间切换\n"
                            "只读 = AI 不能改任何文件;工作区可写 = AI 只能改启动器目录内的文件")
        perm_btn.clicked.connect(self._cycle_permission)
        perm_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #8b96a8; border: 1px solid #3a4150;"
            " border-radius: 6px; padding: 3px 8px; }"
            "QPushButton:hover { color: #ffffff; border-color: #5B8DEF; }")
        self.perm_label = QLabel("")
        perm_row = QHBoxLayout()
        perm_row.setContentsMargins(2, 0, 2, 0)
        perm_row.addWidget(QLabel("文件权限:"))
        perm_row.addWidget(self.perm_label)
        perm_row.addStretch()
        perm_row.addWidget(perm_btn)
        self._update_permission_label()

        row = QHBoxLayout()
        row.addWidget(self.input, 1)

        # 图片行:输入框上方 —— 左侧待发图片缩略图(上下文环已移到发送按钮外圈)
        self.pending_images = []     # [{"path": ...}] 待发送的图片
        self._thumb_widgets = []     # 与 pending_images 一一对应的缩略图 widget
        self.thumb_row = QHBoxLayout()
        self.thumb_row.setContentsMargins(0, 0, 0, 0)
        self.thumb_row.setSpacing(6)
        img_row_widget = QWidget()
        irl = QHBoxLayout(img_row_widget)
        irl.setContentsMargins(2, 2, 2, 0)
        irl.addLayout(self.thumb_row)
        irl.addStretch()
        self.img_row_widget = img_row_widget

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addLayout(top_row)          # 顶部:技能管理入口
        layout.addWidget(self.history, 1)   # 历史区上下弹性伸缩
        layout.addLayout(perm_row)
        layout.addWidget(self.img_row_widget)   # 图片缩略图 + 上下文环
        layout.addLayout(row)
        self.setWidget(container)
        self.setMinimumWidth(320)
        self.setObjectName("AIChatDock")

        self._tool_id = 0              # 工具调用编号
        self._entries = []             # 历史条目(kind, ...),展开时整体重渲染
        self._expanded_tools = set()   # 已展开的工具编号
        self._chat_messages = []       # 真正的对话历史(喂给 LLM 的消息,不含 system)
        self._local_engine = None      # 本地推理引擎(懒加载单例,见 _get_local_engine)
        self._local_downloading = False   # 本地模型下载中标志
        self._local_preloading = False    # 本地模型预热中标志(§8.2 冷启动预加载)
        self._local_dlg = None            # 下载进度弹窗
        self._append_system("AI 助手就绪。选中实例后提问,我会带上实例上下文;"
                            "我还能调用工具(列实例/搜 Mod/读日志等),写操作需要\"工作区可写\"权限。")
        self.update_vision_ui()        # 按模型是否支持多模态显示/隐藏图片按钮
        self.update_local_status()     # 本地模型状态(未下载/已就绪)
        # §8.2 冷启动预加载:若默认就是内置本地模型,开机空闲期就预热 server
        QTimer.singleShot(2000, self.maybe_preload_local)

    def update_vision_ui(self):
        """按所选模型是否支持看图(多模态)显示/隐藏图片相关按钮。

        优先依据模型名判定(见 model_supports_vision);无法判定的本地/自定义模型
        才回退到用户手动的 ai_multimodal 开关。设置对话框保存后也会调用。"""
        vis = model_supports_vision(self.settings.get("ai_provider"),
                                    self.settings.get("ai_model"))
        if vis is None:
            on = bool(self.settings.get("ai_multimodal", False))
        else:
            on = vis
        self.input.set_vision_enabled(on)
        # 模型不支持图片时,清掉还没发送的图片(按钮已隐藏,防止残留)
        if not on and self.pending_images:
            self.pending_images = []
            self._rebuild_thumb_row()
            self._append_system("当前模型不支持图片输入,已清除待发送的图片。")
        self._update_model_badge(vis)

    def _update_model_badge(self, vis):
        """顶部模型徽标:显示当前模型名 + 是否支持看图。"""
        if not hasattr(self, "model_label"):
            return
        model = self.settings.get("ai_model") or "未设置模型"
        if len(model) > 22:
            model = model[:20] + "…"
        if vis is True:
            badge, color = "🖼 支持看图", "#2E7D32"
        elif vis is False:
            badge, color = "🖼 不支持看图", "#8a8f98"
        else:
            cur = bool(self.settings.get("ai_multimodal", False))
            badge, color = ("🖼 手动·开" if cur else "🖼 手动·关"), "#B26A00"
        self.model_label.setText(f"{model} · {badge}")
        self.model_label.setStyleSheet(f"color: {color}; background: transparent;")

    def _vision_on(self) -> bool:
        return bool(self.settings.get("ai_multimodal", False))

    # ---- 文件权限:输入框附近一键切换 ----
    def _update_permission_label(self):
        cur = self.settings.get("ai_permission", "readonly")
        if cur == "workspace_write":
            self.perm_label.setText("工作区可写")
            self.perm_label.setStyleSheet("color: #2E7D32; font-weight: bold;")
        else:
            self.perm_label.setText("只读")
            self.perm_label.setStyleSheet("color: #888888;")

    def _cycle_permission(self):
        """切换 只读 ↔ 工作区可写,立即保存并同步主窗口"""
        cur = self.settings.get("ai_permission", "readonly")
        nxt = "workspace_write" if cur == "readonly" else "readonly"
        self.settings["ai_permission"] = nxt
        self.main.settings["ai_permission"] = nxt
        save_settings(self.settings)
        self._update_permission_label()
        self._append_system(f"文件权限已切换为:{'工作区可写(AI 可改启动器目录内文件)' if nxt == 'workspace_write' else '只读(AI 不能改文件)'}")

    # ---- 消息显示(条目化,支持展开重渲染) ----
    def _append_system(self, text: str):
        self._entries.append(("system", text))
        self._render_all()

    def _append_user(self, text: str):
        self._entries.append(("user", text))
        self._render_all()

    def _append_ai(self, text: str):
        self._entries.append(("ai", text))
        self._render_all()

    def _render_all(self):
        """按条目重绘整个对话流(工具结果展开/收起都在这里决定)"""
        self.history.clear()
        for e in self._entries:
            kind = e[0]
            if kind == "system":
                self.history.append(f'<p style="color:#888888;">{_esc(e[1])}</p>')
            elif kind == "user":
                self.history.append(f'<p><b>你:</b> {_esc(e[1])}</p>')
            elif kind == "ai":
                self.history.append(f'<p><b>AI:</b> {_esc(e[1])}</p>')
            elif kind == "tool":
                # 工具调用:默认折叠成一行摘要,点 [展开] 看完整结果,再点 [收起]
                _k, tid, name, args, result = e
                args_text = ", ".join(f"{k}={v}" for k, v in args.items())[:60] or "(无参数)"
                full = (result or "").strip()
                if tid in self._expanded_tools:
                    self.history.append(
                        f'<p style="color:#888888;">🔧 工具 {name}({_esc(args_text)})'
                        f'<br>&nbsp;&nbsp;→ {_esc(full)} '
                        f'<a href="tool:{tid}">[收起]</a></p>')
                else:
                    preview = (full[:60].replace("\n", " ") + "…") if len(full) > 60 else full
                    self.history.append(
                        f'<p style="color:#888888;">🔧 工具 {name}({_esc(args_text)})'
                        f'<br>&nbsp;&nbsp;→ {_esc(preview)} '
                        f'<a href="tool:{tid}">[展开]</a></p>')
        self._update_ctx_ring()

    def _update_ctx_ring(self):
        """按真实对话历史估算已用上下文 tokens,更新发送按钮外圈的占用环(绿→黄→红)"""
        used = sum(self._est_message(m) for m in self._chat_messages)
        limit = int(self.settings.get("context_window", 65536) or 65536)
        self.input.send_btn.set_usage(used, limit)

    def _show_tool(self, name: str, args: dict, result: str):
        """把一次工具调用记入历史。结果太长默认折叠,点 [展开] 看全文。"""
        self._tool_id += 1
        self._entries.append(("tool", self._tool_id, name, args, result))
        self._render_all()

    # ---- 图片输入 ----
    def _pick_images(self):
        """📷 按钮:打开文件选择框,可多选图片"""
        if not self._vision_on():
            return   # 模型不支持多模态:按钮已隐藏,这里只是兜底
        paths_, _f = QFileDialog.getOpenFileNames(
            self, "添加图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;所有文件 (*)")
        for p in paths_:
            self._add_image_path(p)

    def _pick_recent_screenshots(self):
        """🖼 最近照片:列出 .minecraft 里的游戏截图,选中的添加进输入"""
        if not self._vision_on():
            return   # 模型不支持多模态:按钮已隐藏,这里只是兜底
        import paths as _paths
        dlg = RecentScreenshotsDialog(_paths.GAME_DIR, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            for p in dlg.picked:
                self._add_image_path(p)

    def _add_image_data(self, img: QImage):
        """从剪贴板粘贴的图片:存成临时 png 再走统一添加流程"""
        if img.isNull():
            return
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="aml_img_")
        os.close(fd)
        if img.save(tmp, "PNG"):
            self._add_image_path(tmp)

    def _add_image_path(self, path: str):
        if not self._vision_on():
            self._append_system("⚠️ 当前模型不支持图片输入(设置 → AI 助手 → 多模态 可开启)")
            return
        if not path or not os.path.isfile(path):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size > 8 * 1024 * 1024:
            self._append_system(f"⚠️ 图片超过 8MB,未添加:{os.path.basename(path)}")
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            self._append_system(f"⚠️ 不支持的图片格式:{ext or '(无扩展名)'},支持 png/jpg/webp/gif/bmp")
            return
        self.pending_images.append({"path": path})
        self._rebuild_thumb_row()
        self._append_system(f"📷 已添加图片:{os.path.basename(path)}(发送时随问题一起发给 AI)")

    def _rebuild_thumb_row(self):
        """重建缩略图列表(每张图 42px 缩略图 + 右上角 × 删除)"""
        for w in self._thumb_widgets:
            w.deleteLater()
        self._thumb_widgets = []
        for i, item in enumerate(self.pending_images):
            wrap = QWidget()
            hl = QHBoxLayout(wrap)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            thumb = QLabel()
            pix = QPixmap(item["path"])
            thumb.setPixmap(pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
            thumb.setFixedSize(42, 42)
            thumb.setStyleSheet("border:1px solid #888; border-radius:3px;")
            thumb.setToolTip(os.path.basename(item["path"]))
            x = QPushButton("×")
            x.setFixedSize(16, 16)
            x.setStyleSheet("QPushButton{background:#E53935;color:white;border:none;"
                            "border-radius:8px;font-size:10px;font-weight:bold;}")
            x.setToolTip("移除这张图片")
            x.clicked.connect(lambda _c, idx=i: self._remove_image(idx))
            hl.addWidget(thumb)
            hl.addWidget(x)
            self.thumb_row.addWidget(wrap)
            self._thumb_widgets.append(wrap)

    def _remove_image(self, idx: int):
        if 0 <= idx < len(self.pending_images):
            self.pending_images.pop(idx)
            self._rebuild_thumb_row()

    def _on_anchor(self, url: QUrl):
        """点击对话流里的链接:tool:N 展开/收起工具结果;http(s) 用系统浏览器打开"""
        href = url.toString()
        if href.startswith("tool:"):
            try:
                tid = int(href.split(":", 1)[1])
            except ValueError:
                return
            if tid in self._expanded_tools:
                self._expanded_tools.discard(tid)
            else:
                self._expanded_tools.add(tid)
            self._render_all()
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    # ---- 本地推理(§8.1 拍板 xLAM 模型,grammar 约束) ----
    def _local_enabled(self) -> bool:
        """当前 provider 是否为内置本地模型"""
        return self.settings.get("ai_provider") == LOCAL_PROVIDER

    def _cloud_available(self) -> bool:
        """云端通道是否可用:provider 不是本地模型,且接口地址带 scheme。
        本地模型(ai_base_url 为空)下路由判到 cloud 时,不能拼出 /chat/completions。"""
        if self._local_enabled():
            return False
        base = (self.settings.get("ai_base_url") or "").strip()
        return base.startswith(("http://", "https://"))

    def _cloud_unavailable_hint(self) -> str:
        """§1.3 业务语言:本地模型下没有云端通道时的友好提示(不是技术报错)。"""
        return ("这个任务超出了本地模型的基础能力(比如深度诊断/复杂分析),需要联网的云端模型。"
                "你可以:① 换一种本地模型能处理的说法(装 Mod/查配方/改设置等);"
                "② 在设置 → AI 助手里切换到云端服务(如 DeepSeek),输入密钥即可。")

    def _get_local_engine(self):
        """懒加载本地推理引擎单例(首次用到才起;窗口关闭/游戏启动时 stop)"""
        if self._local_engine is None:
            from local_ai import GrammarToolEngine
            self._local_engine = GrammarToolEngine(model_id=LOCAL_MODEL_ID)
        return self._local_engine

    def _local_model_ready(self) -> bool:
        """模型文件是否已下载且校验通过(§2 懒加载:没下就提示+走云端)"""
        try:
            import model_registry
            return model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            return False

    def _local_tool_call(self, text: str, executor, on_tool):
        """本地路径:grammar 工具调用 → 复用 executor 执行。
        返回 (reply 文本, 是否成功);失败时上层落云端(§1.4)。"""
        self.signals.local_status.emit("本地模型:推理中…")
        try:
            engine = self._get_local_engine()
            engine.start()   # 幂等:已启动则直接返回
            # 注入真实启动器上下文(§7.3 最轻量 RAG):实例清单 + 设置,避免模型乱编实例 id
            try:
                from local_ai import build_launcher_context
                context = build_launcher_context()
            except Exception:
                context = ""
            call = engine.tool_call(text, context=context)
            name = call.get("name", "")
            args = call.get("arguments", {})
            if not name:
                return ("(本地模型未给出明确动作)", False)
            if on_tool:
                on_tool(name, args, "(本地推理)")
            result = executor(name, args)
            # 工具结果作为回复展示(本地单轮,不做多轮,规划 §0)
            text_result = str(result)
            reply = f"✅ 已执行「{name}」:\n{text_result}"
            return (reply, True)
        except PermissionDenied:
            return ("权限拒绝:当前是只读权限,不能修改文件(可在 AI 设置中改为\"工作区可写\")", True)
        except Exception as e:
            return (f"(本地推理失败:{type(e).__name__}: {e})", False)
        finally:
            self.signals.local_status.emit(self._local_status_text())

    # ---- 本地模型下载(懒加载 §2):首次用到且未下载 → 后台下载带进度,期间走云端 ----
    def _start_local_download(self):
        """主线程:创建下载进度弹窗,后台线程下载模型(镜像优先),完成后关闭弹窗。"""
        if self._local_downloading:
            return
        if not bool(self.settings.get("ai_local_auto_download", True)):
            return
        self._local_downloading = True
        self._on_local_status("本地模型:下载中 0%…")
        dlg = QProgressDialog("正在下载本地模型(约500MB,镜像优先)…", None, 0, 0, self)
        dlg.setWindowTitle("下载本地模型")
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.show()
        self._local_dlg = dlg

        def dl():
            try:
                import model_registry
                model_registry.download(
                    LOCAL_MODEL_ID,
                    progress_callback=lambda d, t: self.signals.local_dl_progress.emit(d, t))
                self.signals.local_dl_done.emit("✅ 本地模型下载完成,之后可用内置本地模型。")
            except Exception as e:
                self.signals.local_dl_done.emit(
                    f"❌ 本地模型下载失败:{type(e).__name__}: {str(e)[:200]}(可稍后重新触发)")

        threading.Thread(target=dl, daemon=True).start()

    def _on_local_dl_progress(self, done, total):
        """主线程:更新下载进度弹窗 + 状态栏文字(跨线程信号已搬回主线程)。"""
        if self._local_dlg is not None:
            self._local_dlg.setMaximum(max(total, 1))
            self._local_dlg.setValue(done)
            if total:
                self._local_dlg.setLabelText(
                    f"下载本地模型…  {done/1024/1024:.0f} / {total/1024/1024:.0f} MB")
        if self._local_enabled():
            self._on_local_status(
                f"本地模型:下载中 {done/1024/1024:.0f}MB…" if total
                else "本地模型:下载中…")

    def _on_local_dl_done(self, msg):
        """主线程:下载结束,关弹窗 + 提示 + 刷新状态。"""
        self._local_downloading = False
        if self._local_dlg is not None:
            self._local_dlg.close()
            self._local_dlg = None
        self._append_system(msg)
        self.update_local_status()

    # ---- 本地模型状态显示(未下载/下载中/预加载/已就绪/推理中) ----
    def _local_status_text(self) -> str:
        """本地模型当前状态文字(只读,不碰 UI,可在任意线程算)。"""
        try:
            import model_registry
            ready = model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            ready = False
        if getattr(self, "_local_preloading", False):
            return "本地模型:预热中…"
        if self._local_downloading:
            return "本地模型:下载中…"
        if ready:
            return "本地模型:已就绪"
        return "本地模型:未下载\n(首次使用会自动下载)"

    def _on_local_status(self, text: str):
        """主线程:更新顶部本地模型状态标签。"""
        if not hasattr(self, "local_status_label"):
            return
        if not self._local_enabled():
            self.local_status_label.setVisible(False)
            return
        self.local_status_label.setVisible(True)
        self.local_status_label.setText(text)
        if "中" in text:          # 预热中/下载中/推理中 → 进行中
            color = "#B26A00"      # 进行中:橙
        elif "已就绪" in text:
            color = "#2E7D32"      # 就绪:绿
        else:
            color = "#8a8f98"
        self.local_status_label.setStyleSheet(f"color: {color}; background: transparent;")

    def update_local_status(self):
        """按当前 provider/下载状态刷新本地模型状态标签(主线程)。"""
        if self._local_enabled():
            self._on_local_status(self._local_status_text())
        elif hasattr(self, "local_status_label"):
            self.local_status_label.setVisible(False)

    # ---- 冷启动预加载(§8.2):本地 provider 且模型已下载时,后台预热 llama-server ----
    def maybe_preload_local(self):
        """空闲时预热本地模型,让首次本地提问不再等 server 冷启动。

        仅当:选的是内置本地模型、模型已下载、且当前未在预热/未在运行时才触发。
        游戏启动时会按 ai_in_game 决定是否 stop(见 launch_selected),两者不冲突:
        预热只在这不干扰游戏内存时进行。"""
        if not self._local_enabled():
            return
        try:
            import model_registry
            if not model_registry.is_downloaded(LOCAL_MODEL_ID):
                return
        except Exception:
            return
        if getattr(self, "_local_preloading", False):
            return
        eng = getattr(self, "_local_engine", None)
        if eng is not None and getattr(eng, "proc", None) and eng.proc.poll() is None:
            return   # 已在运行
        self._local_preloading = True
        self._on_local_status("本地模型:预热中…")

        def warm():
            try:
                engine = self._get_local_engine()
                engine.start()   # 阻塞直至 /health 就绪(后台线程,不卡 UI)
            except Exception:
                pass
            finally:
                self._local_preloading = False
                self.signals.local_status.emit(self._local_status_text())

        threading.Thread(target=warm, daemon=True).start()

    # ---- 本地引擎生命周期:游戏启动/窗口关闭时卸载(省内存/无残留进程) ----
    def stop_local_engine(self):
        """卸载本地模型引擎(llama-server 进程)。off/cloud 时游戏启动会调用;窗口关闭也会调用。"""
        eng = getattr(self, "_local_engine", None)
        if eng is not None:
            try:
                eng.stop()
            except Exception:
                pass
            self._local_engine = None     # 下次要用会重新懒加载

    def shutdown(self):
        """窗口关闭时调用:卸载本地模型,确保无残留进程。"""
        self.stop_local_engine()

    # ---- 发送(后台线程,带工具调用,过程实时显示) ----
    def ask(self, text: str):
        """直接发起一次 AI 对话(自动 debug 等场景用)"""
        self.input.setText(text)
        self.send()

    def send(self):
        text = self.input.text().strip()
        images = list(self.pending_images)
        if images and not self._vision_on():
            # 模型不支持多模态的兜底:忽略待发图片
            self._append_system("⚠️ 当前模型不支持图片输入,已忽略待发送的图片。")
            images = []
            self.pending_images = []
            self._rebuild_thumb_row()
        if not text and not images:
            return
        if not self._confirm_if_heavy(text):
            return   # 用户取消:保留输入,不发送
        self.input.clear()
        if text.startswith("/"):
            # 以 / 开头的输入 = 直接给运行中的游戏发指令(如 /summon zombie),不走 AI
            from game_command import send_command
            result = send_command(text, self.main)
            self._append_system(f"🎮 {result}")
            return
        self._append_user(text + (f"  [📷×{len(images)}]" if images else ""))
        self._append_system("⏳ 正在请求 AI...")
        # 无图片时 content 保持纯字符串(省 token、兼容老接口);有图片才用多模态 list
        # (OpenAI 兼容 data URL 格式;模型不支持视觉会报错提示)
        content = text
        if images:
            content = []
            if text:
                content.append({"type": "text", "text": text})
            for item in images:
                try:
                    with open(item["path"], "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                except OSError as e:
                    self._append_system(f"⚠️ 读取图片失败:{os.path.basename(item['path'])} ({e})")
                    continue
                mime = mimetypes.guess_type(item["path"])[0] or "image/png"
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{b64}"}})
        self.pending_images = []
        self._rebuild_thumb_row()
        # 真正的多轮记忆:历史消息(含工具调用)保存在 _chat_messages,
        # 每次发送 = 最新 system + 历史 + 当前问题
        self._chat_messages.append({"role": "user", "content": content})
        self._trim_history()
        messages = [
            {"role": "system", "content": self.main.ai_context()},
        ] + list(self._chat_messages)
        s = self.settings
        executor = build_executor(s)
        tools_called = []
        is_local = self._local_enabled()

        def on_tool(name, args, result):
            tools_called.append(name)
            self.signals.tool_called.emit(name, args, result)   # 跨线程安全:信号回主线程渲染

        def worker():
            try:
                # 路由分流(§1):本地 provider 时先判规则/难度/歧义
                if is_local and not images:
                    from task_router import route, match_rule
                    decision = route(text)
                    if decision["target"] == "rule":
                        reply = match_rule(text) or "(没想好怎么答,稍后再试试)"
                        self.signals.reply.emit(reply)
                        self._update_ctx_ring()
                        return
                    if decision["target"] == "local":
                        if self._local_model_ready():
                            reply, ok = self._local_tool_call(text, executor, on_tool)
                            if ok:
                                if tools_called:
                                    self.signals.no_tool.emit()
                                self.signals.reply.emit(reply)
                                self._update_ctx_ring()
                                return
                            # 本地失败 → 有云端则落云端,否则友好提示(§1.3/§1.4)
                            if self._cloud_available():
                                self._append_system("本地推理未成功,已转云端处理…")
                            else:
                                self.signals.reply.emit(self._cloud_unavailable_hint())
                                self._update_ctx_ring()
                                return
                        else:
                            # 模型未下载(§2 懒加载):提示后走云端;同时后台触发下载(带进度弹窗)
                            self._append_system("本地模型未下载,先走云端(设置里可关本地模型)。"
                                                "首次使用会在后台下载约 500MB…")
                            self.signals.local_dl_start.emit()
                            if not self._cloud_available():
                                # 本地模型也没下、云端也没有 → 无法继续,友好提示
                                self.signals.reply.emit(
                                    "本地模型还没下载,而且当前没有可用的云端服务。"
                                    "模型正在后台下载,下载完成后就能离线用了;"
                                    "或者到设置里配置云端服务(如 DeepSeek)。")
                                self._update_ctx_ring()
                                return
                    # decision==ask 或模型未就绪:落云端(ask 由云端循环触发 ask_user 交互)
                    if not self._cloud_available():
                        # 本地模式下路由判到 cloud/ask 但没有云端通道 → 友好提示,不拼空 URL
                        self.signals.reply.emit(self._cloud_unavailable_hint())
                        self._update_ctx_ring()
                        return
                result = chat_with_tools(messages, s, TOOLS, executor,
                                         on_tool=on_tool, on_user_ask=self.on_user_ask,
                                         return_messages=True)
                if isinstance(result, tuple):
                    reply, working = result
                    # 存回完整历史(去掉 system,下次重新生成)
                    self._chat_messages = [m for m in working
                                           if m.get("role") != "system"]
                else:   # 兼容旧 mock(返回字符串)
                    reply = result
                if not tools_called:
                    self.signals.no_tool.emit()
                self.signals.reply.emit(reply)
                self._update_ctx_ring()
            except Exception as e:
                self.signals.error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _est_message(self, m: dict) -> int:
        """估算一条消息的 token 数(支持多模态 content list)"""
        content = m.get("content")
        if isinstance(content, list):
            text = " ".join(str(c.get("text", "")) for c in content
                            if isinstance(c, dict) and c.get("type") == "text")
            return estimate_tokens(text)
        return estimate_tokens(str(content or ""))

    def _confirm_if_heavy(self, new_text: str) -> bool:
        """对话已用较多上下文时,发送前弹提示(这可需要不少 token),问是否继续。
        用户取消 → 保留输入框内容,不发送。"""
        from PySide6.QtWidgets import QMessageBox
        limit = int(self.settings.get("context_window", 65536) or 65536)
        used = sum(self._est_message(m) for m in self._chat_messages)
        used += estimate_tokens(new_text)
        if used <= int(limit * 0.6):
            return True
        ret = QMessageBox.question(
            self, "继续对话?",
            f"当前对话已用约 {used / 1000:.1f}k tokens(占上下文 {used * 100 // limit}%)。\n"
            "继续这一轮会消耗不少 token,确定要继续吗?\n\n"
            "(选择\"No\"可保留输入内容,或开启新对话后重发)")
        return ret == QMessageBox.StandardButton.Yes

    def _trim_history(self):
        """上下文超限时丢弃最早的消息(保留最近的,让对话能继续)"""
        limit = int(self.settings.get("context_window", 65536) or 65536)
        budget = int(limit * 0.7)   # 给回复留 30%
        while len(self._chat_messages) > 1:
            used = sum(self._est_message(m) for m in self._chat_messages)
            if used <= budget:
                break
            self._chat_messages.pop(0)   # 丢最早的一条(保留刚发的当前问题)
        self._update_ctx_ring()

    def _on_no_tool(self):
        self._append_system(
            "⚠️ 本轮对话模型没有调用任何工具。如果它只是说\"我将...\"而没动手,"
            "说明当前模型不支持工具调用(小模型常见),建议换更强的模型,"
            "或用 🛠 自测确认。")

    # ---- ask_user 交互:AI 不确定时弹选择框(多选 + 输入补充) ----
    def on_user_ask(self, question: str, options: list) -> str:
        """worker 线程调用:请求主线程弹窗,阻塞等用户选择,返回选择文本"""
        result_box = []
        ev = threading.Event()
        self.signals.user_ask.emit(question, options, result_box, ev)
        ev.wait()   # 等主线程弹窗完成
        picked = result_box[0] if result_box else []
        if not picked:
            return "用户取消了选择(未给答案)。请根据上下文自行处理,或向用户说明你需要的选择。"
        return "用户选择了:" + "、".join(str(p) for p in picked)

    def _on_user_ask_ui(self, question, options, result_box, ev):
        """主线程:弹 AskUserDialog,结果放回 result_box 并唤醒 worker"""
        try:
            dlg = AskUserDialog(question, options, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                result_box.append(dlg.selected())
            else:
                result_box.append([])
        finally:
            ev.set()

    # ---- 自测工具调用 ----
    def self_test_tools(self):
        self._append_system("🛠 正在自测:让模型调用 list_instances 工具...")
        messages = [
            {"role": "system", "content": "请调用 list_instances 工具,把结果原样告诉我。不要只描述计划。"},
            {"role": "user", "content": "测试工具调用"},
        ]
        tools_called = []

        def on_tool(name, args, result):
            tools_called.append(name)
            self.signals.tool_called.emit(name, args, result)   # 跨线程安全

        def worker():
            try:
                chat_with_tools(messages, self.settings, TOOLS,
                                build_executor(self.settings), on_tool=on_tool)
                self.signals.self_test.emit(bool(tools_called))
            except Exception as e:
                self.signals.error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_self_test(self, ok: bool):
        if ok:
            self._append_system("✅ 自测通过:模型能正常调用工具。")
        else:
            self._append_system(
                "❌ 自测失败:模型没有调用任何工具。它可能不支持工具调用——\n"
                "建议换模型:qwen2.5-14b/32b-instruct 等支持工具调用的模型,"
                "或云端 DeepSeek(工具调用很稳);在 LM Studio 里确认模型的"
                "chat template 支持 function calling。")

    def _on_reply(self, text: str):
        self._append_ai(text)

    def _on_error(self, err: str):
        self._append_system(f"请求失败:{err}")

    # ---- 技能管理(入口在 AI 子窗口顶部) ----
    def open_skill_manager(self):
        if self.main is not None and hasattr(self.main, "open_skill_manager"):
            self.main.open_skill_manager()
        else:
            self._append_system("技能管理需要在主窗口打开")

    # ---- 设置 ----
    def open_settings(self):
        dlg = AISettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.settings
            self.main.settings = dlg.settings
            save_settings(dlg.settings)
            self.update_vision_ui()   # 多模态开关变化 → 立即显示/隐藏图片按钮
            self._append_system("AI 设置已保存")
