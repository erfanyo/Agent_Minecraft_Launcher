# -*- coding: utf-8 -*-
"""
首次启动引导界面(只出现一次,之后随时可在"设置"里改):
1. 选择 Minecraft 游戏文件存放位置 —— 可以是全新目录,也可以是已有的
   .minecraft(比如 PCL2 / 官方启动器创建的),启动器会直接读取里面的实例。
   一个用户有多个 .minecraft 时,引导里浏览选择用哪一个即可。
2. 第一次配置 AI 助手(DeepSeek / Ollama / LM Studio / 自定义)。
"""
import os

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import paths
from assistant import AISettingsForm
from settings import load_settings, save_settings


class OnboardingDialog(QDialog):
    """两步引导:游戏目录 → AI 配置。保存进 config.json。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 Agent Minecraft Launcher")
        self.setMinimumSize(580, 500)
        self.settings = load_settings()

        # ---- 页面 1:选择游戏目录 ----
        page_path = QWidget()
        title1 = QLabel("第一步 · 选择游戏文件位置")
        title1.setStyleSheet("font-size: 16px; font-weight: bold;")
        desc = QLabel(
            "Minecraft 的所有文件(版本、依赖库、资源、Java)都会放在你选定的目录里。\n"
            "可以是全新空目录(启动器自动创建),也可以是已经存在的 .minecraft——\n"
            "比如 PCL2 / 官方启动器创建的,启动器会直接读取里面的实例。")
        desc.setWordWrap(True)

        self.path_edit = QLineEdit(self.settings.get("game_dir") or paths.DEFAULT_GAME_DIR)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse)
        default_btn = QPushButton("用默认位置")
        default_btn.setToolTip("回到启动器目录下的 .minecraft")
        default_btn.clicked.connect(lambda: self.path_edit.setText(paths.DEFAULT_GAME_DIR))

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)

        self.path_info = QLabel("")
        self.path_info.setWordWrap(True)
        self.path_edit.textChanged.connect(self._check_path)

        p1 = QVBoxLayout(page_path)
        p1.addWidget(title1)
        p1.addWidget(desc)
        p1.addSpacing(12)
        p1.addLayout(path_row)
        p1.addWidget(default_btn)
        p1.addWidget(self.path_info)
        p1.addStretch()

        # ---- 页面 2:AI 首次配置 ----
        page_ai = QWidget()
        title2 = QLabel("第二步 · 配置 AI 助手(可以稍后改)")
        title2.setStyleSheet("font-size: 16px; font-weight: bold;")
        desc2 = QLabel("AI 助手能回答问题、诊断报错、帮你装 Mod。首次配置一次,"
                       "以后随时在菜单 设置 / AI 设置 里修改。")
        desc2.setWordWrap(True)
        self.ai_form = AISettingsForm(self.settings)
        hint = QLabel("没有 DeepSeek 账号?可以先用 Ollama / LM Studio 本地模型,完全免费离线。\n"
                      "注意:发图片需要模型本身会\"看图\",本地模型通常不支持,不确定就别勾。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888888;")
        builtin_hint = QLabel("💡 也可以直接用「内置本地 AI 模型」:离线可用、无需密钥,"
                              "首次用到时自动下载(约 500MB,镜像优先)。")
        builtin_hint.setWordWrap(True)
        builtin_hint.setStyleSheet("color: #888888;")

        p2 = QVBoxLayout(page_ai)
        p2.addWidget(title2)
        p2.addWidget(desc2)
        p2.addSpacing(12)
        p2.addWidget(self.ai_form)
        p2.addWidget(hint)
        p2.addWidget(builtin_hint)
        p2.addStretch()

        self.stack = QStackedWidget()
        self.stack.addWidget(page_path)
        self.stack.addWidget(page_ai)

        # ---- 底部按钮 ----
        self.prev_btn = QPushButton("上一步")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton("下一步")
        self.next_btn.clicked.connect(self._next)
        skip_btn = QPushButton("跳过(AI 以后再配)")
        skip_btn.setToolTip("先保存游戏目录,AI 用默认设置,以后在 设置 里改")
        skip_btn.clicked.connect(self._finish)

        btn_row = QHBoxLayout()
        btn_row.addWidget(skip_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.prev_btn)
        btn_row.addWidget(self.next_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)
        layout.addLayout(btn_row)

        self._check_path()

    # ---- 页面切换 ----
    def _prev(self):
        self.stack.setCurrentIndex(0)
        self.prev_btn.setEnabled(False)
        self.next_btn.setText("下一步")

    def _next(self):
        if self.stack.currentIndex() == 0:
            self.stack.setCurrentIndex(1)
            self.prev_btn.setEnabled(True)
            self.next_btn.setText("完成")
        else:
            self._finish()

    # ---- 路径选择与检测 ----
    def _browse(self):
        start = self.path_edit.text().strip() or paths.DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 Minecraft 文件目录", start)
        if d:
            self.path_edit.setText(d)

    def _check_path(self):
        p = self.path_edit.text().strip()
        if not p:
            self.path_info.setText("")
            return
        if not os.path.isdir(p):
            self.path_info.setText("⚠️ 该目录还不存在——启动器会自动创建它。")
            return
        if paths.looks_like_game_dir(p):
            versions = os.path.join(p, "versions")
            n, names = 0, []
            if os.path.isdir(versions):
                for name in sorted(os.listdir(versions)):
                    if os.path.isdir(os.path.join(versions, name)) and not name.startswith("."):
                        n += 1
                        if len(names) < 5:
                            names.append(name)
            extra = "、".join(names) + ("…" if n > 5 else "")
            if n:
                self.path_info.setText(f"✅ 检测到 .minecraft 目录,里面有 {n} 个实例:\n{extra}")
            else:
                self.path_info.setText("✅ 这是一个 .minecraft 目录(目前还没有实例)。")
        else:
            self.path_info.setText("这是一个普通文件夹,启动器会把它当成全新的游戏目录使用。")

    # ---- 保存并关闭 ----
    def _finish(self):
        self.settings["game_dir"] = self.path_edit.text().strip()
        self.settings.update(self.ai_form.values())
        save_settings(self.settings)
        paths.set_game_dir(self.settings["game_dir"])
        self.accept()
