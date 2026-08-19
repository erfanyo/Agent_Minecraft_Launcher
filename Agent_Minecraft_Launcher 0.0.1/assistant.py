# -*- coding: utf-8 -*-
"""
AI 助手:停靠在主窗口右侧的对话栏(类似 VS Code 的 AI 侧栏)。

- 接 OpenAI 兼容接口:DeepSeek(默认)/ Ollama 本地 / 自定义
- 对话在后台线程跑,回复经信号回到主线程,不卡界面
- 主窗口通过 ai_context() 提供上下文(选中的实例、启动器设置等)作为系统提示
"""
import html
import json
import threading

import requests
from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
    _tool("install_mod", "给某实例安装 Mod(写操作,需要工作区写权限;会先自动备份)",
          {"slug": {"type": "string"}, "instance": {"type": "string"},
           "version": {"type": "string", "description": "可选,指定版本"}},
          ["slug", "instance"]),
    _tool("backup_instance", "备份某实例:存档打包 zip + 模组列表 txt(写操作)",
          {"instance": {"type": "string"}}, ["instance"]),
    _tool("set_setting", "修改启动器设置,如 memory_gb=6(写操作)",
          {"key": {"type": "string"}, "value": {"type": "string"}}, ["key", "value"]),
]

# 写操作工具:执行前必须过"工作区可写"权限检查
WRITE_TOOLS = {"install_mod", "backup_instance", "set_setting"}


def build_executor(settings: dict):
    """构造工具执行器:LLM 只能"提议",真正执行在这里,权限检查也在这里。"""
    import agent_tools

    def executor(name: str, args: dict) -> str:
        # 动态查找:函数名 == 工具名,便于测试打桩与后续扩展
        fn = getattr(agent_tools, name, None)
        if fn is None:
            return f"错误:未知工具 {name}"
        if name in WRITE_TOOLS:
            require_workspace_write(settings)  # 只读权限 → 直接拒绝
        # 灵感 #6:写操作前先自动备份(装 Mod 前防坏档)
        if name == "install_mod":
            try:
                backup_note = agent_tools.backup_instance(args.get("instance", ""))
            except Exception as e:
                backup_note = f"(备份失败:{e})"
            result = fn(**args)
            return f"[已自动备份:{backup_note}]\n{result}"
        return str(fn(**args))

    return executor


def chat_with_tools(messages: list, settings: dict, tools: list,
                    executor, max_rounds: int = 6, on_tool=None) -> str:
    """带工具调用的对话循环:LLM 提议 → 执行 → 结果回传 → 直到完成。

    tools 为 None 时退化为普通对话。
    on_tool(name, args, result) 每执行一个工具就回调一次(供界面显示过程)。
    返回最终回复文本。"""
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
            return msg.get("content") or ""
        for call in tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = executor(name, args)
            except PermissionDenied as e:
                result = f"权限拒绝:{e}"
            except Exception as e:
                result = f"工具执行失败:{type(e).__name__}: {e}"
            if on_tool:
                on_tool(name, args, result)
            working.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return "(达到最大工具轮数,已停止。可以让我继续,或拆分任务。)"


class _Signals(QObject):
    reply = Signal(str)
    error = Signal(str)
    no_tool = Signal()
    self_test = Signal(bool)


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


class AISettingsDialog(QDialog):
    """AI 服务设置:服务商 / 接口地址 / 密钥 / 模型"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 助手设置")
        self.setMinimumWidth(380)
        self.settings = dict(settings)

        self.provider = QComboBox()
        self.provider.addItem("DeepSeek(推荐,便宜)", "deepseek")
        self.provider.addItem("Ollama 本地(免费离线)", "ollama")
        self.provider.addItem("LM Studio(本地 llama.cpp)", "lmstudio")
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

        form = QFormLayout()
        form.addRow("服务:", self.provider)
        form.addRow("接口地址:", self.base_url)
        form.addRow("API 密钥:", self.api_key)
        form.addRow("模型:", self.model)
        form.addRow("文件权限:", self.permission)

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
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)

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

    def accept(self):
        self.settings.update({
            "ai_provider": self.provider.currentData(),
            "ai_base_url": self.base_url.text().strip(),
            "ai_api_key": self.api_key.text().strip(),
            "ai_model": self.model.text().strip(),
            "ai_permission": self.permission.currentData(),
        })
        super().accept()


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

        self.history = QTextBrowser()
        self.history.anchorClicked.connect(self._on_anchor)  # 自己处理链接(展开工具日志/开外部链接)
        self.input = QLineEdit()
        self.input.setPlaceholderText("问 AI 任何问题(自动带上当前实例上下文)…")
        self.input.returnPressed.connect(self.send)
        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self.send)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedWidth(30)
        settings_btn.setToolTip("AI 设置")
        settings_btn.clicked.connect(self.open_settings)
        test_btn = QPushButton("🛠")
        test_btn.setFixedWidth(30)
        test_btn.setToolTip("自测工具调用:让模型调用一个工具,看它支不支持")
        test_btn.clicked.connect(self.self_test_tools)

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(send_btn)
        row.addWidget(test_btn)
        row.addWidget(settings_btn)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.history)
        layout.addLayout(row)
        self.setWidget(container)
        self.setMinimumWidth(320)
        self.setObjectName("AIChatDock")

        self._tool_id = 0              # 工具调用编号
        self._entries = []             # 历史条目(kind, ...),展开时整体重渲染
        self._expanded_tools = set()   # 已展开的工具编号
        self._append_system("AI 助手就绪。选中实例后提问,我会带上实例上下文;"
                            "我还能调用工具(列实例/搜 Mod/读日志等),写操作需要\"工作区可写\"权限。")

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
                _k, tid, name, args, result = e
                args_text = ", ".join(f"{k}={v}" for k, v in args.items())[:80] or "(无参数)"
                full = (result or "").strip()
                if len(full) > 120 and tid not in self._expanded_tools:
                    preview = full[:120].replace("\n", " ") + "…"
                    self.history.append(
                        f'<p style="color:#888888;">🔧 工具 {name}({_esc(args_text)})'
                        f'<br>&nbsp;&nbsp;→ {_esc(preview)} '
                        f'<a href="tool:{tid}">[展开]</a></p>')
                else:
                    self.history.append(
                        f'<p style="color:#888888;">🔧 工具 {name}({_esc(args_text)})'
                        f'<br>&nbsp;&nbsp;→ {_esc(full)}</p>')

    def _show_tool(self, name: str, args: dict, result: str):
        """把一次工具调用记入历史。结果太长默认折叠,点 [展开] 看全文。"""
        self._tool_id += 1
        self._entries.append(("tool", self._tool_id, name, args, result))
        self._render_all()

    def _on_anchor(self, url: QUrl):
        """点击对话流里的链接:tool:N 展开工具结果;http(s) 用系统浏览器打开"""
        href = url.toString()
        if href.startswith("tool:"):
            try:
                tid = int(href.split(":", 1)[1])
            except ValueError:
                return
            self._expanded_tools.add(tid)
            self._render_all()
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    # ---- 发送(后台线程,带工具调用,过程实时显示) ----
    def send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append_user(text)
        self._append_system("⏳ 正在请求 AI...")
        messages = [
            {"role": "system", "content": self.main.ai_context()},
            {"role": "user", "content": text},
        ]
        s = self.settings
        executor = build_executor(s)
        tools_called = []

        def on_tool(name, args, result):
            tools_called.append(name)
            self._show_tool(name, args, result)

        def worker():
            try:
                reply = chat_with_tools(messages, s, TOOLS, executor, on_tool=on_tool)
                if not tools_called:
                    self.signals.no_tool.emit()
                self.signals.reply.emit(reply)
            except Exception as e:
                self.signals.error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _show_tool(self, name: str, args: dict, result: str):
        """把一次工具调用显示在对话流里。
        结果太长默认折叠,点 [展开] 再看全文。"""
        self._tool_id += 1
        self._entries.append(("tool", self._tool_id, name, args, result))
        self._render_all()

    def _on_anchor(self, url: QUrl):
        """点击对话流里的链接:tool:N 展开工具结果;http(s) 用系统浏览器打开"""
        href = url.toString()
        if href.startswith("tool:"):
            try:
                tid = int(href.split(":", 1)[1])
            except ValueError:
                return
            self._expanded_tools.add(tid)
            self._render_all()
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    def _on_no_tool(self):
        self._append_system(
            "⚠️ 本轮对话模型没有调用任何工具。如果它只是说\"我将...\"而没动手,"
            "说明当前模型不支持工具调用(小模型常见),建议换更强的模型,"
            "或用 🛠 自测确认。")

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
            self._show_tool(name, args, result)

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

    # ---- 设置 ----
    def open_settings(self):
        dlg = AISettingsDialog(self.settings, self)
        if dlg.exec():
            self.settings = dlg.settings
            self.main.settings = dlg.settings
            save_settings(dlg.settings)
            self._append_system("AI 设置已保存")
