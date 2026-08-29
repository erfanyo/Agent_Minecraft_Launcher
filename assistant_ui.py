# -*- coding: utf-8 -*-
"""
AI 助手的纯表现层 UI 单元(从 assistant.py 拆分而来,降低主文件体积)。

**为什么拆**:assistant.py 原 2719 行,混合了「AI 核心逻辑(工具/executor/路由)」与
「纯 UI 表现(圆环/输入框/弹窗/纯函数)」。这里放**边界清晰、不反向引用核心内部状态**的
单元——它们只依赖 Qt 与少量纯函数,抽走后 assistant.py 专注于核心,维护性更好。

放入本模块的元素(均不引用 assistant 的 TOOLS/executor/worker):
- 纯函数:_esc / estimate_tokens / model_supports_vision(+_VISION_MODEL_HINTS) / collect_screenshots
- 纯 UI 类:ContextRing / SendWithRing / RecentScreenshotsDialog / AskUserDialog / _ChatInput

被 assistant.py 经 `from assistant_ui import ...` 复用。
"""
import html
import os
import time

from ui_style import muted_color, success_color, warning_color, danger_color, accent_color
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ---------------- 纯工具函数 ----------------
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


# ---------------- 纯 UI 类 ----------------
class ContextRing(QWidget):
    """小圆环:显示上下文占用比例(绿→黄→红),悬停显示具体数字。
    样式与下载指示器(DownloadIndicator)一致,只是更小、中心显示百分比。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._used = 0
        self._limit = 1
        self._color = success_color()
        self.setFixedSize(30, 30)
        self.setToolTip("上下文占用")
        self.setStyleSheet("background: transparent;")

    def set_usage(self, used: int, limit: int):
        self._used = max(used, 0)
        self._limit = max(limit, 1)
        ratio = min(1.0, self._used / self._limit)
        if ratio < 0.6:
            self._color = success_color()
        elif ratio < 0.85:
            self._color = warning_color()
        else:
            self._color = danger_color()
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


class SendWithRing(QWidget):
    """发送按钮 + 外圈上下文占用环(表示方式与下载指示器一致):
    发送按钮缩小居中,外圈环形显示上下文已用比例,绿→黄→红。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._used = 0
        self._limit = 1
        self._color = success_color()
        self.setFixedSize(40, 40)
        self.setToolTip("发送(Enter) | 上下文: 0%")
        self.setStyleSheet("background: transparent;")
        self.btn = QPushButton("↑", self)
        self.btn.setFixedSize(26, 26)
        self.btn.move(7, 7)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            f"QPushButton{{border-radius:13px; background:#3E7CB1; color:white;"
            f" font-size:15px; font-weight:bold; border:none;}}"
            f"QPushButton:hover{{background:{accent_color()};}}"
            f"QPushButton:pressed{{background:#2E5A85;}}")
        self.btn.clicked.connect(self.clicked.emit)

    def click(self):
        self.btn.click()

    def set_usage(self, used: int, limit: int):
        self._used = max(used, 0)
        self._limit = max(limit, 1)
        ratio = min(1.0, self._used / self._limit)
        if ratio < 0.6:
            self._color = success_color()
        elif ratio < 0.85:
            self._color = warning_color()
        else:
            self._color = danger_color()
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
            hint.setStyleSheet(f"color: {muted_color()};")
        else:
            hint = QLabel(f"共找到最近 {len(shots)} 张截图:双击添加,或选中多张点[添加]")
            hint.setStyleSheet(f"color: {muted_color()};")
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
        ok_btn.setDefault(True)          # 回车=确定;高亮落在确定而不是取消
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setAutoDefault(False)  # 取消绝不因回车被触发(误触=拒绝,不合逻辑)
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
        # 焦点落到输入框:用户可直接打字,回车即「确定」
        self.input.setFocus()

    def selected(self) -> list:
        """收集:勾选项 + 输入补充(非空)"""
        picked = [c.text() for c in self.checks if c.isChecked()]
        extra = self.input.text().strip()
        if extra:
            picked.append(extra)
        return picked


class _ChatInput(QPlainTextEdit):
    """AI 输入框:多行 + 自带滚动条,Enter 发送、Shift+Enter 换行;
    右下角内置圆形 ↑ 发送按钮 + 🛠 工具测试按钮 + 📷 图片按钮(挨着发送)。
    支持粘贴图片(触发 imagePasted)。兼容旧 QLineEdit 接口(setText/text),方便测试与外部代码。"""
    returnPressed = Signal()
    sendClicked = Signal()
    testClicked = Signal()
    imageClicked = Signal()
    recentClicked = Signal()
    voiceClicked = Signal()          # 🎤 语音输入(现为占位,ASR 接入后可用)
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
        # 语音输入:微信式(接管光标,把识别文字插到光标处)。现为占位,ASR 接入后可用。
        self.voice_btn = QPushButton("🎤", self)
        self.voice_btn.setFixedSize(30, 30)
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.setToolTip("语音输入(微信式·接管光标;识别待接入,先占位)")
        self.voice_btn.setStyleSheet(
            "QPushButton{border-radius:15px; background:rgba(128,128,128,90);"
            " font-size:14px; border:none;}"
            "QPushButton:hover{background:rgba(128,128,128,160);}")
        self.voice_btn.clicked.connect(self.voiceClicked.emit)
        # 右下角按钮顺序(从右到左):发送环 → 🛠 → 📷 → 🖼 → 🎤
        # 📷/🖼 是图片相关按钮,模型不支持多模态时隐藏(见 set_vision_enabled)
        self._corner_btns = [self.send_btn, self.test_btn, self.img_btn, self.recent_btn, self.voice_btn]
        self._vision = True
        self._has_model = True            # 是否已选择模型(未选择时隐藏发送/自测按钮)

    def set_has_model(self, on: bool):
        """未选择模型时隐藏「发送」与「自测工具调用」按钮,并禁用发送,避免空模型空转。"""
        self._has_model = bool(on)
        self.send_btn.setVisible(self._has_model)
        self.test_btn.setVisible(self._has_model)
        self._refresh_placeholder()
        self._layout_corner_buttons()   # 重新摆放右下角按钮

    def model_selected(self) -> bool:
        return self._has_model

    def set_vision_enabled(self, on: bool):
        """按模型是否支持多模态显示/隐藏图片相关按钮(📷 添加图片、🖼 最近截图)"""
        self._vision = bool(on)
        self.img_btn.setVisible(self._vision)
        self.recent_btn.setVisible(self._vision)
        self._refresh_placeholder()      # 重新生成占位文案(考虑是否已选模型)
        self._layout_corner_buttons()   # 重新摆放右下角按钮

    def _refresh_placeholder(self):
        """根据 已选模型 与 多模态 状态生成输入框占位文案。"""
        if not self._has_model:
            self.setPlaceholderText("请先在设置 → AI 助手里选择模型")
        elif self._vision:
            self.setPlaceholderText("问 AI 任何问题…(Enter 发送, Shift+Enter 换行;Ctrl+V 可粘贴图片)")
        else:
            self.setPlaceholderText("问 AI 任何问题…(Enter 发送, Shift+Enter 换行)")

    def vision_enabled(self) -> bool:
        return self._vision

    def _layout_corner_buttons(self):
        """把右下角圆形按钮从右到左依次摆放,只排可见的按钮"""
        if self.width() <= 0 or self.height() <= 0:
            return   # 尺寸未就绪(启动时)不摆,等 showEvent/resizeEvent
        m = 6
        x = self.width() - m
        for b in reversed(self._corner_btns):
            if not b.isVisible():
                continue
            x -= b.width() + m
            b.move(x, self.height() - b.height() - m)

    def showEvent(self, e):
        super().showEvent(e)
        # 启动时控件尺寸可能为 0 导致按钮错位到左上角;显示后重摆一次
        self._layout_corner_buttons()

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
