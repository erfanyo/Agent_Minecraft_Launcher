# -*- coding: utf-8 -*-
"""
首次启动引导界面(只出现一次,之后随时可在"设置"里改):
1. 选择 Minecraft 游戏文件存放位置 —— 可以是全新目录,也可以是已有的
   .minecraft(比如 PCL2 / 官方启动器创建的),启动器会直接读取里面的实例。
   一个用户有多个 .minecraft 时,引导里浏览选择用哪一个即可。
2. 按需配置 AI 云端 API。
"""
from __future__ import annotations
import json
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import paths
from assistant import AIQuickSettingsForm
from settings import load_settings, save_settings


class _ChoiceCard(QFrame):
    """新手 / 老手选择卡:上面一张插图(缺图时退回占位符),下面小字标注;点击选中(单选)。"""

    clicked = Signal()

    def __init__(self, title: str, subtitle: str, colors: dict,
                 tip: str = "", image_path: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("onboard_choice")
        self._colors = dict(colors)
        self._checked = False
        self._source = None                 # 原图(未缩放),resize 时重新适配
        self._last_box = (0, 0)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if tip:
            self.setToolTip(tip)

        column = QVBoxLayout(self)
        column.setContentsMargins(12, 12, 12, 10)
        column.setSpacing(8)

        # ① 插图(找不到文件就显示占位符)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(140)
        if image_path and os.path.isfile(image_path):
            pm = QPixmap(image_path)
            if not pm.isNull():
                self._source = pm
        if self._source is None:
            self.image.setText("🖼")
            self.image.setToolTip("图片占位:以后放一张插图")
        else:
            self.image.setToolTip("")
        # ② 下面小字标注
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)

        column.addWidget(self.image, 1)
        column.addWidget(self.title)
        column.addWidget(self.subtitle, 0)
        self._refresh()

    # ---- 插图:按当前标签尺寸等比缩放(居中),尺寸变了才重算,避免递归 ----
    def _fit_image(self):
        c = self._colors
        if self._source is None:
            self.image.setPixmap(QPixmap())     # 先清掉旧图(这一步会连带清空文字)
            self.image.setText("🖼")             # 再补占位文字
            self.image.setStyleSheet(
                f"QLabel {{ background: {c['btn_bg']}; border: 1px dashed {c['border']};"
                f" border-radius: 8px; color: {c['muted']}; font-size: 26px; }}")
            return
        box = (max(self.image.width(), 80), max(self.image.height(), 120))
        if box == self._last_box and not self.image.pixmap().isNull():
            return
        self._last_box = box
        dpr = self.devicePixelRatioF() or 1.0
        scaled = self._source.scaled(
            int(box[0] * dpr), int(box[1] * dpr),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self.image.setPixmap(scaled)
        self.image.setStyleSheet("QLabel { background: transparent; border: none; }")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_image()

    # ---- 选中状态(与 QRadioButton 接口一致,便于沿用旧逻辑) ----
    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool):
        on = bool(on)
        if on == self._checked:
            return
        self._checked = on
        self._refresh()

    def _refresh(self):
        c = self._colors
        border = c["accent"] if self._checked else c["border"]
        width = 2 if self._checked else 1
        bg = c["sel"] if self._checked else c["base"]
        self.setStyleSheet(
            f"QFrame#onboard_choice {{ background: {bg}; border: {width}px solid {border};"
            " border-radius: 10px; }")
        self._fit_image()
        self.title.setStyleSheet(
            f"QLabel {{ color: {c['text']}; font-weight: bold; font-size: 14px;"
            " background: transparent; }")
        self.subtitle.setStyleSheet(
            f"QLabel {{ color: {c['muted']}; font-size: 11px; background: transparent; }}")

    # ---- 交互:鼠标或键盘(空格/回车)都能选 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class OnboardingDialog(QDialog):
    """首次启动引导:① 新手/老手 ② 游戏目录 ③ 可选 AI 配置。保存进 config.json。

    新手→自动播放引导式教程;老手→跳过(设置→系统 可重播)。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("欢迎使用 Agent Minecraft Launcher")
        # 教程页含图文截图,窗口太小会看不全 → 放宽默认尺寸
        self.setMinimumSize(900, 680)
        self.resize(1000, 780)
        self.settings = load_settings()
        self.want_tutorial = False   # 用户在第一步是否选了「新手」(决定是否自动播教程)
        self._confirmed_risky_path = ""
        # 对话框统一主题背景(深浅色自适应);页面本身透明,避免「白边」
        # 注意:父级一旦设置样式表,Qt 引擎会接管渲染,子控件文字会回退为默认黑色
        # (深浅色系统都可能「黑底黑字」),所以必须在这里把所有控件类型显式上色。
        from ui_style import current_color, set_style, text_color, muted_color, is_dark_mode
        _dlg_bg = current_color("bg1")   # 不透明背景,避免 QSS 半透明画成黑块
        _text = text_color()
        _muted = muted_color()
        _base = current_color("bg0")
        _border = current_color("panel_border")
        _btn_bg = current_color("btn_bg")
        _sel = current_color("sel_bg")
        self.setObjectName("onboarding_dialog")
        self.setStyleSheet(
            f"QDialog#onboarding_dialog {{ background: {_dlg_bg}; color: {_text}; }}"
            f"QDialog#onboarding_dialog QLabel {{ color: {_text}; background: transparent; }}"
            f"QDialog#onboarding_dialog QGroupBox {{ color: {_text}; background: transparent;"
            f" border: 1px solid {_border}; border-radius: 8px; margin-top: 12px; }}"
            f"QDialog#onboarding_dialog QGroupBox::title {{ color: {_muted};"
            f" subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
            f"QDialog#onboarding_dialog QLineEdit, QDialog#onboarding_dialog QSpinBox {{"
            f" color: {_text}; background: {_base}; border: 1px solid {_border};"
            f" border-radius: 6px; padding: 4px 8px; }}"
            f"QDialog#onboarding_dialog QComboBox {{ color: {_text}; background: {_btn_bg};"
            f" border: 1px solid {_border}; border-radius: 6px; padding: 3px 8px; }}"
            f"QDialog#onboarding_dialog QComboBox QAbstractItemView {{ background: {_base};"
            f" color: {_text}; selection-background-color: {_sel}; border: 1px solid {_border}; }}"
            f"QDialog#onboarding_dialog QCheckBox {{ color: {_text}; background: transparent; spacing: 6px; }}"
        )
        # 页面内容透明,避免默认白底
        for _w in (): pass
        self.setAutoFillBackground(False)

        # ---- 页面 0:新手 / 老手 ----
        page_welcome = QWidget()
        title0 = QLabel("欢迎!先确认一下你对 Minecraft 熟悉程度")
        title0.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {_text};")
        desc0 = QLabel(
            "接下来先选好游戏目录。AI 助手是可选增强，想用时再配置即可。\n"
            "如果你是第一次接触本启动器(或想熟悉一下),选「新手」,"
            "配置完成后会**自动带你走一遍新手教程**。")
        desc0.setWordWrap(True)

        # 左右两张选择卡(上=图片占位,下=小字标注)
        choice_colors = {
            "accent": current_color("accent"), "border": _border, "sel": _sel,
            "base": _base, "btn_bg": _btn_bg, "text": _text, "muted": _muted,
        }
        # 插图:onboarding-images/ 下的透明底 PNG(缺图则自动退回占位符)
        img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onboarding-images")
        self.rb_new = _ChoiceCard(
            "新手", "第一次用 / 想熟悉一下（推荐，自动进教程）", choice_colors,
            tip="配置完成后自动播放引导式新手教程;以后随时可在 设置→系统→重播引导教程",
            image_path=os.path.join(img_dir, "newbie.png"))
        self.rb_old = _ChoiceCard(
            "老手", "我懂 Minecraft，自己摸索就行", choice_colors,
            tip="不自动进教程;需要时可在 设置→系统→重播引导教程",
            image_path=os.path.join(img_dir, "veteran.png"))
        self._choice_cards = [self.rb_new, self.rb_old]
        for card in self._choice_cards:
            card.clicked.connect(lambda c=card: self._select_choice(c))
        self.rb_new.setChecked(True)

        choice_row = QHBoxLayout()
        choice_row.setSpacing(14)
        choice_row.addWidget(self.rb_new, 1)
        choice_row.addWidget(self.rb_old, 1)

        p0 = QVBoxLayout(page_welcome)
        p0.addWidget(title0)
        p0.addWidget(desc0)
        p0.addSpacing(10)
        p0.addLayout(choice_row, 1)
        p0.addStretch()

        # ---- 页面 1:选择游戏目录 ----
        page_path = QWidget()
        title1 = QLabel("第一步 · 选择游戏文件位置")
        title1.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {_text};")
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

        # 文字前面放一个文件夹图标(先用系统原生图标:Windows 11 显示原生文件夹样式;
        # 以后其它系统要专属图标,换这里的 pixmap 即可)
        folder_icon = QLabel()
        folder_icon.setPixmap(self.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon).pixmap(32, 32))
        folder_icon.setFixedSize(40, 40)
        folder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_row = QHBoxLayout()
        desc_row.setSpacing(10)
        desc_row.addWidget(folder_icon, 0, Qt.AlignmentFlag.AlignTop)
        desc_row.addWidget(desc, 1)

        p1 = QVBoxLayout(page_path)
        p1.addWidget(title1)
        p1.addLayout(desc_row)
        p1.addSpacing(12)
        p1.addLayout(path_row)
        p1.addWidget(default_btn)
        p1.addWidget(self.path_info)
        p1.addStretch()

        # ---- 页面 2:连接 AI 助手(配置 + 硅基流动教程,两者放一起) ----
        page_ai = QWidget()
        title2 = QLabel("可选 · 连接 AI 助手")
        title2.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {_text};")
        desc2 = QLabel("先在上面填好接口；下面是免费拿密钥的图文教程，照着做即可。"
                       "配置后可在「设置 → 模型」随时调整。")
        desc2.setWordWrap(True)
        self.ai_form = AIQuickSettingsForm(self.settings)
        local_limit = QLabel(
            "本地模型的优势是离线可用，但内置模型较小，主要适合基础问答和简单、明确的指令。"
            "面对复杂推理、多步规划或模糊描述（例如按功能推荐 Mod）时，可能理解不准或选错工具；"
            "需要这类能力时建议配置云端模型。")
        local_limit.setWordWrap(True)
        local_limit.setStyleSheet(f"color: {_muted};")

        # 教程(图文 Markdown,与配置同页)
        tut_title = QLabel("📖 教程 · 免费拿硅基流动(SiliconFlow) API 密钥")
        tut_title.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {_text};")
        tut_browser = QTextBrowser()
        tut_browser.setOpenExternalLinks(True)
        tut_browser.setStyleSheet(
            f"QTextBrowser {{ background: transparent; color: {_text}; border: none; }}")
        _root = os.path.dirname(os.path.abspath(__file__))
        md_path = os.path.join(_root, "docs", "siliconflow-tutorial.md")
        # 文档基址设为 docs/,教程里的相对图片路径(../docs-assets/...)才能解析
        tut_browser.document().setBaseUrl(
            QUrl.fromLocalFile(os.path.join(_root, "docs") + os.sep))
        try:
            with open(md_path, encoding="utf-8") as f:
                tut_browser.setMarkdown(f.read())
        except Exception:
            tut_browser.setMarkdown("(教程加载失败，可查看 docs/siliconflow-tutorial.md)")

        p2 = QVBoxLayout(page_ai)
        p2.addWidget(title2)
        p2.addWidget(desc2)
        p2.addSpacing(8)
        p2.addWidget(self.ai_form)
        p2.addWidget(local_limit)
        p2.addSpacing(10)
        p2.addWidget(tut_title)
        p2.addWidget(tut_browser, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(page_welcome)
        self.stack.addWidget(page_path)
        self.stack.addWidget(page_ai)

        # ---- 底部按钮(包进一个带顶部分隔线的 footer,避免与页面内容重叠/被白边压住) ----
        self.prev_btn = QPushButton("上一步")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._prev)
        self.next_btn = QPushButton("下一步")
        self.next_btn.clicked.connect(self._next)
        from ui_style import current_color, set_style, card_btn_style
        for b in (self.prev_btn, self.next_btn):
            set_style(b, card_btn_style)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self.prev_btn)
        btn_row.addWidget(self.next_btn)

        # footer 容器:顶部分隔线 + 背景,占满底行,按钮不会被页面"白边"压住
        footer = QWidget()
        footer.setObjectName("onboard_footer")
        footer.setStyleSheet(
            "#onboard_footer { background: %s; border-top: 1px solid %s; }"
            % (_dlg_bg, _border))
        f_lay = QVBoxLayout(footer)
        f_lay.setContentsMargins(14, 10, 14, 12)
        f_lay.addLayout(btn_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(footer)

        self._check_path()

    # ---- 新手 / 老手 单选 ----
    def _select_choice(self, card):
        for c in getattr(self, "_choice_cards", []):
            c.setChecked(c is card)

    # ---- 页面切换 ----
    def _prev(self):
        idx = self.stack.currentIndex()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
        self.prev_btn.setEnabled(self.stack.currentIndex() > 0)
        self.next_btn.setText("完成" if self.stack.currentIndex() == self.stack.count() - 1 else "下一步")

    def _next(self):
        idx = self.stack.currentIndex()
        if idx == 1 and not self._confirm_path():
            return
        if idx < self.stack.count() - 1:
            self.stack.setCurrentIndex(idx + 1)
            self.prev_btn.setEnabled(True)
            self.next_btn.setText("完成" if idx + 1 == self.stack.count() - 1 else "下一步")
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
        self._confirmed_risky_path = ""
        if not p:
            self.path_info.setText("❌ 还没有选择游戏文件夹。")
            return
        assessment = assess_game_path(p)
        issues = [f"❌ {item}" for item in assessment.errors]
        issues += [f"⚠️ {item}" for item in assessment.warnings]
        prefix = "\n".join(issues)
        if not os.path.isdir(p):
            normal = "该目录还不存在，确认后启动器会自动创建它。"
            self.path_info.setText("\n".join(filter(None, (prefix, normal))))
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
                normal = f"✅ 检测到 .minecraft 目录，里面有 {n} 个实例：\n{extra}"
            else:
                normal = "✅ 这是一个 .minecraft 目录（目前还没有实例）。"
        else:
            normal = "这是一个普通文件夹，启动器会把它当成全新的游戏目录使用。"
        self.path_info.setText("\n".join(filter(None, (prefix, normal))))

    def _confirm_path(self) -> bool:
        path = self.path_edit.text().strip()
        assessment = assess_game_path(path)
        if assessment.errors:
            QMessageBox.warning(self, "换一个文件夹", "\n".join(assessment.errors))
            self.stack.setCurrentIndex(1)
            self.prev_btn.setEnabled(True)
            return False
        normalized = os.path.normcase(os.path.abspath(path))
        if assessment.warnings and self._confirmed_risky_path != normalized:
            box = QMessageBox(self)
            box.setWindowTitle("这个位置可能带来问题")
            box.setText("\n".join(assessment.warnings))
            box.setInformativeText("建议改到简短的英文路径，例如 D:\\AMCL\\.minecraft。")
            change = box.addButton("返回修改", QMessageBox.ButtonRole.AcceptRole)
            keep = box.addButton("仍然使用", QMessageBox.ButtonRole.DestructiveRole)
            box.setDefaultButton(change)
            box.exec()
            if box.clickedButton() is not keep:
                self.stack.setCurrentIndex(1)
                self.prev_btn.setEnabled(True)
                return False
            self._confirmed_risky_path = normalized
        return True

    # ---- 保存并关闭 ----
    def _finish(self):
        if not self._confirm_path():
            return
        self.settings["game_dir"] = self.path_edit.text().strip()
        self.settings.update(self.ai_form.values())
        # 首次引导:若磁盘上的 config.json 没存过内存(说明是首次/默认),按机器物理内存给合理默认
        import os
        from settings import suggested_memory_gb, CONFIG_PATH
        _saved_mem = None
        try:
            if os.path.exists(CONFIG_PATH):
                _saved_mem = json.load(open(CONFIG_PATH, encoding="utf-8")).get("memory_gb")
        except Exception:
            _saved_mem = None
        if _saved_mem is None:
            self.settings["memory_gb"] = 0  # 每次启动时按当前可用内存计算
        # 记录是否要自动进新手教程(新手→播;老手→跳过,随时可重播)
        self.want_tutorial = self.rb_new.isChecked()
        save_settings(self.settings)
        paths.set_game_dir(self.settings["game_dir"])
        self.accept()


# ===================== Merged from path_validation.py =====================
"""Plain-language checks for the game directory selected during onboarding."""

from dataclasses import dataclass
import os
import tempfile


@dataclass(frozen=True)
class PathAssessment:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _inside(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(parent)]) == os.path.normcase(parent)
    except (OSError, ValueError):
        return False


def assess_game_path(path: str, environment=None) -> PathAssessment:
    """Find early path problems without creating or changing any directories."""
    raw = (path or "").strip()
    if not raw:
        return PathAssessment(errors=("还没有选择游戏文件夹。",))
    expanded = os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
    errors = []
    warnings = []

    if os.path.exists(expanded) and not os.path.isdir(expanded):
        errors.append("这里是一个文件，不是文件夹。")
    ancestor = expanded
    while ancestor and not os.path.exists(ancestor):
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            break
        ancestor = parent
    if ancestor and os.path.exists(ancestor) and not os.access(ancestor, os.W_OK):
        errors.append("这个位置不能写入，请换到你有权限的文件夹。")

    if any(ord(char) > 127 for char in expanded):
        warnings.append("路径含中文或特殊字符；少数旧 Java、加载器或驱动可能无法识别。")
    # Preserve the user's raw spelling: POSIX abspath turns a Windows UNC path
    # into a local-looking path before this check runs in cross-platform CI.
    if raw.startswith("\\\\") or expanded.startswith("\\\\"):
        warnings.append("这是网络共享位置；断网或共享断开时，游戏和 Java 会无法启动。")
    if len(expanded) > 120:
        warnings.append("路径已经很长，安装 Mod 后可能超过 Windows 的长度限制。")

    env = os.environ if environment is None else environment
    temp_root = os.path.abspath(tempfile.gettempdir())
    if _inside(expanded, temp_root):
        warnings.append("这是临时文件夹，Windows 清理空间时可能把游戏一起删除。")
    onedrive = (env.get("OneDrive") or env.get("OneDriveConsumer") or "").strip()
    if onedrive and _inside(expanded, os.path.abspath(onedrive)):
        warnings.append("这是同步盘目录，文件同步可能与游戏更新互相冲突。")

    return PathAssessment(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)))


# ===================== Merged from path_validation.py =====================
"""Plain-language checks for the game directory selected during onboarding."""

from dataclasses import dataclass
import os
import tempfile


@dataclass(frozen=True)
class PathAssessment:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _inside(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(parent)]) == os.path.normcase(parent)
    except (OSError, ValueError):
        return False


def assess_game_path(path: str, environment=None) -> PathAssessment:
    """Find early path problems without creating or changing any directories."""
    raw = (path or "").strip()
    if not raw:
        return PathAssessment(errors=("还没有选择游戏文件夹。",))
    expanded = os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
    errors = []
    warnings = []

    if os.path.exists(expanded) and not os.path.isdir(expanded):
        errors.append("这里是一个文件，不是文件夹。")
    ancestor = expanded
    while ancestor and not os.path.exists(ancestor):
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            break
        ancestor = parent
    if ancestor and os.path.exists(ancestor) and not os.access(ancestor, os.W_OK):
        errors.append("这个位置不能写入，请换到你有权限的文件夹。")

    if any(ord(char) > 127 for char in expanded):
        warnings.append("路径含中文或特殊字符；少数旧 Java、加载器或驱动可能无法识别。")
    # Preserve the user's raw spelling: POSIX abspath turns a Windows UNC path
    # into a local-looking path before this check runs in cross-platform CI.
    if raw.startswith("\\\\") or expanded.startswith("\\\\"):
        warnings.append("这是网络共享位置；断网或共享断开时，游戏和 Java 会无法启动。")
    if len(expanded) > 120:
        warnings.append("路径已经很长，安装 Mod 后可能超过 Windows 的长度限制。")

    env = os.environ if environment is None else environment
    temp_root = os.path.abspath(tempfile.gettempdir())
    if _inside(expanded, temp_root):
        warnings.append("这是临时文件夹，Windows 清理空间时可能把游戏一起删除。")
    onedrive = (env.get("OneDrive") or env.get("OneDriveConsumer") or "").strip()
    if onedrive and _inside(expanded, os.path.abspath(onedrive)):
        warnings.append("这是同步盘目录，文件同步可能与游戏更新互相冲突。")

    return PathAssessment(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)))
