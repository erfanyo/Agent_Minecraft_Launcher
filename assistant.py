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
from PySide6.QtCore import QObject, QSize, Qt, QUrl, Signal
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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ai_actions import PERMISSIONS, PermissionDenied, permission_instructions, require_workspace_write
from agent_tools import TOOL_FUNCS
from settings import save_settings


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
    _tool("install_instance", "下载/创建游戏实例(写操作,需要工作区写权限)。"
          "可创建原版,或带加载器的实例(fabric/forge/neoforge)。"
          "加载器版本留空=自动用最新;可选装 Fabric API / 光影 / 优化 Mod。"
          "注意:加载器实例会自动下载它依赖的基础原版;整个下载可能要几分钟,"
          "期间请等待,不要重复调用;完成后会返回实例 id",
          {"version": {"type": "string", "description": "游戏版本,如 1.21.1 / 1.20.1 / 26.3-snapshot-8"},
           "loader": {"type": "string", "description": "加载器:fabric/forge/neoforge,留空=原版"},
           "loader_version": {"type": "string", "description": "可选,加载器版本(留空=最新)"},
           "shader": {"type": "boolean", "description": "是否装光影加载器,默认 false"},
           "optimize": {"type": "boolean", "description": "是否装优化 Mod(钠/锂等),默认 false"},
           "fabric_api_version": {"type": "string", "description": "可选,Fabric API 版本(留空不装)"}},
          ["version"]),
    _tool("ask_user", "拿不准用户想要什么时调用:向用户弹出选择框(可多选,可输入补充),"
          "用户的选择会作为结果返回给你。用于任务拆分中途确认方向/确认选项,"
          "不要用一次调用问太多问题",
          {"question": {"type": "string", "description": "问题,如 你想装哪些 Mod?"},
           "options": {"type": "array", "items": {"type": "string"},
                       "description": "候选选项,用户可多选(如 [\"钠\",\"锂\",\"玉\",\"JEI\"])"}},
          ["question"]),
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
    _tool("compare_items", "比较物品参数(武器伤害/护甲/护甲韧性/攻速/挖掘等级),返回最强的 N 个",
          {"attribute": {"type": "string", "description": "武器伤害 / 护甲 / 挖掘等级 等"},
           "top_n": {"type": "integer", "description": "返回前几名,默认 10"}},
          ["attribute"]),
]

# 写操作工具:执行前必须过"工作区可写"权限检查
WRITE_TOOLS = {"install_mod", "install_mods", "install_instance", "backup_instance", "set_setting"}


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


class AISettingsForm(QWidget):
    """AI 服务设置表单(可嵌入对话框 / 首次引导页):服务商 / 接口 / 密钥 / 模型 / 权限"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.provider = QComboBox()
        self.provider.addItem("DeepSeek(推荐,便宜)", "deepseek")
        self.provider.addItem("Ollama 本地(免费离线)", "ollama")
        self.provider.addItem("LM Studio(本地 llama.cpp)", "lmstudio")
        self.provider.addItem("OpenRouter(聚合,含视觉模型)", "openrouter")
        self.provider.addItem("硅基流动 SiliconFlow(国内)", "siliconflow")
        self.provider.addItem("智谱 GLM(国内)", "zhipu")
        self.provider.addItem("通义千问 DashScope(国内)", "dashscope")
        self.provider.addItem("自定义(OpenAI 兼容)", "custom")
        self.base_url = QLineEdit(settings.get("ai_base_url", ""))
        self.api_key = QLineEdit(settings.get("ai_api_key", ""))
        self.api_key.setPlaceholderText("留空 = 无需密钥(Ollama 本地)")
        self.model = QLineEdit(settings.get("ai_model", ""))
        self.permission = QComboBox()
        for label, value in PERMISSIONS:
            self.permission.addItem(label, value)
        cur = settings.get("ai_permission", "readonly")
        idx = self.permission.findData(cur)
        self.permission.setCurrentIndex(idx if idx >= 0 else 0)
        self.context_window = QSpinBox()
        self.context_window.setRange(1000, 1000000)
        self.context_window.setSingleStep(1024)
        self.context_window.setValue(int(settings.get("context_window", 65536) or 65536))
        self.context_window.setSuffix(" tokens")
        self.context_window.setToolTip("模型上下文窗口上限,用于对话框里的占用圆环显示")

        form = QFormLayout(self)
        form.addRow("服务:", self.provider)
        form.addRow("接口地址:", self.base_url)
        form.addRow("API 密钥:", self.api_key)
        form.addRow("模型:", self.model)
        form.addRow("文件权限:", self.permission)
        form.addRow("上下文窗口:", self.context_window)

        self.provider.currentIndexChanged.connect(self._fill_defaults)
        self._fill_defaults()

    def _fill_defaults(self):
        idx = self.provider.currentData()
        if idx == "deepseek":
            self.base_url.setText("https://api.deepseek.com/v1")
            self.model.setText("deepseek-chat")
        elif idx == "ollama":
            self.base_url.setText("http://localhost:11434/v1")
            self.model.setText("qwen2.5:7b")
        elif idx == "lmstudio":
            self.base_url.setText("http://localhost:1234/v1")
            self.model.clear()
            self.model.setPlaceholderText("输入你已在 LM Studio 加载的模型名")
        elif idx == "openrouter":
            self.base_url.setText("https://openrouter.ai/api/v1")
            self.model.setText("deepseek/deepseek-chat-v3-0324:free")
        elif idx == "siliconflow":
            self.base_url.setText("https://api.siliconflow.cn/v1")
            self.model.setText("Qwen/Qwen2.5-7B-Instruct")
        elif idx == "zhipu":
            self.base_url.setText("https://open.bigmodel.cn/api/paas/v4")
            self.model.setText("glm-4-flash")
        elif idx == "dashscope":
            self.base_url.setText("https://dashscope.aliyuncs.com/compatible-mode/v1")
            self.model.setText("qwen-plus")

    def values(self) -> dict:
        """收集表单内容为设置字段"""
        return {
            "ai_provider": self.provider.currentData(),
            "ai_base_url": self.base_url.text().strip(),
            "ai_api_key": self.api_key.text().strip(),
            "ai_model": self.model.text().strip(),
            "ai_permission": self.permission.currentData(),
            "context_window": self.context_window.value(),
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
        self.provider = self.form.provider
        self.base_url = self.form.base_url
        self.api_key = self.form.api_key
        self.model = self.form.model
        self.permission = self.form.permission
        self.context_window = self.form.context_window

        hint = QLabel("DeepSeek 需要 API key(platform.deepseek.com 申请,极便宜);\n"
                      "Ollama / LM Studio 都是本地 llama.cpp,无需密钥:\n"
                      "LM Studio 默认接口 http://localhost:1234/v1,模型填你已加载的名字。\n"
                      "文件权限:只读 = AI 不能改任何文件;工作区可写 = AI 只能改启动器目录内的文件")
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 圆形按钮钉在输入框右下角(发送环在最后,🛠 在它左边,📷 再左边,🖼 最左)
        m = 6
        bw = self.send_btn.width()   # 发送环 40px(含外圈上下文环)
        self.send_btn.move(self.width() - bw - m, self.height() - bw - m)
        self.test_btn.move(self.width() - bw * 2 - m * 2, self.height() - bw - m)
        self.img_btn.move(self.width() - bw * 3 - m * 3, self.height() - bw - m)
        self.recent_btn.move(self.width() - bw * 4 - m * 4, self.height() - bw - m)

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

        self.history = QTextBrowser()
        self.history.anchorClicked.connect(self._on_anchor)  # 自己处理链接(展开工具日志/开外部链接)
        self.input = _ChatInput()
        self.input.setPlaceholderText("问 AI 任何问题…(Enter 发送, Shift+Enter 换行;Ctrl+V 可粘贴图片)")
        self.input.returnPressed.connect(self.send)
        self.input.sendClicked.connect(self.send)
        self.input.testClicked.connect(self.self_test_tools)   # 🛠 已移进输入框,挨着发送
        self.input.imageClicked.connect(self._pick_images)
        self.input.imagePasted.connect(self._add_image_data)
        self.input.recentClicked.connect(self._pick_recent_screenshots)
        # 浮动/停靠使用 QDockWidget 标题栏右上角自带的浮动按钮(与系统行为整合)

        # 顶部:技能管理入口(相对靠上,一眼可见)
        skills_btn = QPushButton("技能管理…")
        skills_btn.setToolTip("管理游戏运行时辅助技能(指令指南/崩溃守护等)")
        skills_btn.clicked.connect(self.open_skill_manager)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(2, 0, 2, 0)
        top_row.addWidget(QLabel("AI 助手"))
        top_row.addStretch()
        top_row.addWidget(skills_btn)

        # 文件权限:放在输入框附近,一眼可见、一键切换(不藏进二级菜单)
        perm_btn = QPushButton("切换")
        perm_btn.setFixedWidth(44)
        perm_btn.setToolTip("在 只读 / 工作区可写 之间切换\n"
                            "只读 = AI 不能改任何文件;工作区可写 = AI 只能改启动器目录内的文件")
        perm_btn.clicked.connect(self._cycle_permission)
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
        self._append_system("AI 助手就绪。选中实例后提问,我会带上实例上下文;"
                            "我还能调用工具(列实例/搜 Mod/读日志等),写操作需要\"工作区可写\"权限。")

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
        paths, _f = QFileDialog.getOpenFileNames(
            self, "添加图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.gif *.bmp);;所有文件 (*)")
        for p in paths:
            self._add_image_path(p)

    def _pick_recent_screenshots(self):
        """🖼 最近照片:列出 .minecraft 里的游戏截图,选中的添加进输入"""
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

    # ---- 发送(后台线程,带工具调用,过程实时显示) ----
    def ask(self, text: str):
        """直接发起一次 AI 对话(自动 debug 等场景用)"""
        self.input.setText(text)
        self.send()

    def send(self):
        text = self.input.text().strip()
        images = list(self.pending_images)
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

        def on_tool(name, args, result):
            tools_called.append(name)
            self.signals.tool_called.emit(name, args, result)   # 跨线程安全:信号回主线程渲染

        def worker():
            try:
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
            self._append_system("AI 设置已保存")
