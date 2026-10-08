# -*- coding: utf-8 -*-
"""
AI 助手的纯表现层 UI 单元(从 assistant.py 拆分而来,降低主文件体积)。

**为什么拆**:assistant.py 原 2719 行,混合了「AI 核心逻辑(工具/executor/路由)」与
「纯 UI 表现(圆环/输入框/弹窗/纯函数)」。这里放**边界清晰、不反向引用核心内部状态**的
单元——它们只依赖 Qt 与少量纯函数,抽走后 assistant.py 专注于核心,维护性更好。

放入本模块的元素(均不引用 assistant 的 TOOLS/executor/worker):
- 纯函数:_esc / estimate_tokens / model_supports_vision(+_VISION_MODEL_HINTS) / collect_screenshots
- 纯 UI 类:ContextRing / SendWithRing / RecentScreenshotsDialog / AskUserDialog / AskUserPanel / _ChatInput

被 assistant.py 经 `from assistant_ui import ...` 复用。
"""
import html
import os
import time

from ui_style import (
    accent_color,
    current_color,
    danger_color,
    muted_color,
    popup_menu_style,
    set_style,
    success_color,
    text_color,
    warning_color,
)
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
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
        self.setFixedSize(28, 28)
        self.setToolTip("发送(Enter) | 上下文: 0%")
        self.setStyleSheet("background: transparent;")
        self.btn = QPushButton("↑", self)
        self.btn.setFixedSize(20, 20)
        self.btn.move(4, 4)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet(
            f"QPushButton{{border-radius:10px; background:#3E7CB1; color:white;"
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


class ChoicePopupButton(QPushButton):
    """无箭头的文字选择按钮，弹出带标题、说明和选中标记的菜单。"""

    currentIndexChanged = Signal(int)

    def __init__(self, choices=(), current=0, parent=None):
        super().__init__(parent)
        self._choices = []
        self._current = -1
        self._menu = QMenu(self)
        self._menu.setStyleSheet(
            f"QMenu {{ background: {current_color('panel_bg')}; color: {current_color('text')};"
            f" border: 1px solid {current_color('panel_border')}; border-radius: 12px; padding: 6px; }}")
        self._menu.aboutToShow.connect(self._populate_menu)
        self.clicked.connect(self._show_menu)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"QPushButton {{ color: {current_color('text')}; background: {current_color('panel_bg')};"
            f" border: 1px solid {current_color('panel_border')}; border-radius: 16px; padding: 6px 12px; }}"
            f"QPushButton:hover {{ border-color: {accent_color()}; }}")
        for choice in choices:
            self.addItem(*choice)
        if self._choices:
            self.setCurrentIndex(current)

    def addItem(self, label: str, value, description: str = ""):
        self._choices.append((str(label), value, str(description)))

    def findData(self, value) -> int:
        return next((i for i, choice in enumerate(self._choices) if choice[1] == value), -1)

    def setCurrentIndex(self, index: int):
        if not self._choices:
            return
        index = max(0, min(int(index), len(self._choices) - 1))
        changed = index != self._current
        self._current = index
        self.setText(self._choices[index][0])
        if changed:
            self.currentIndexChanged.emit(index)

    def currentIndex(self) -> int:
        return self._current

    def currentData(self):
        return self._choices[self._current][1] if self._current >= 0 else None

    def _show_menu(self):
        self._menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    def _populate_menu(self):
        self._menu.clear()
        for index, (label, _value, description) in enumerate(self._choices):
            row = QPushButton()
            row.setMinimumWidth(310)
            row.setMinimumHeight(60)
            mark = "✓" if index == self._current else ""
            row.setText(
                f"<table width='100%'><tr><td><b>{_esc(label)}</b></td>"
                f"<td align='right'>{mark}</td></tr>"
                f"<tr><td colspan='2'><span style='color:{muted_color()}'>"
                f"{_esc(description)}</span></td></tr></table>")
            row.setToolTip(description)
            row.setStyleSheet(
                f"QPushButton {{ text-align: left; color: {current_color('text')};"
                f" background: transparent; border: none; border-radius: 8px; padding: 8px 10px; }}"
                f"QPushButton:hover {{ background: {current_color('btn_bg')}; }}")
            action = QWidgetAction(self._menu)
            action.setDefaultWidget(row)
            self._menu.addAction(action)
            row.clicked.connect(lambda _checked=False, i=index: self._choose(i))

    def _choose(self, index: int):
        self.setCurrentIndex(index)
        self._menu.hide()


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


class OptionCard(QPushButton):
    """卡片式单选行:点击切换选中;选中=蓝框 + 浅蓝底 + ✓,未选中=细边框。
    跟随主题配色(set_style 登记,换色自动刷新)。"""

    def __init__(self, label: str, value, description: str = "", parent=None):
        super().__init__(parent)
        self.value = value
        self._on = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(description)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(52)
        self._label = QLabel(label)
        self._desc = QLabel(description)
        self._desc.setWordWrap(True)
        self._mark = QLabel("")
        self._mark.setFixedWidth(18)
        self._mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.addWidget(self._label)
        text_col.addWidget(self._desc)
        row.addLayout(text_col, 1)
        row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self._apply()

    def set_on(self, on: bool):
        self._on = bool(on)
        self.blockSignals(True)
        self.setChecked(self._on)
        self.blockSignals(False)
        self._apply()

    def _apply(self):
        accent = accent_color()
        text = text_color()
        muted = muted_color()
        if self._on:
            border = accent
            bw = "2px"
            bg = current_color("sel_bg")
            self._mark.setText(f"<span style='color:{accent};font-size:16px;font-weight:bold;'>&#10003;</span>")
            label_css = f"color: {text}; font-size: 13px; font-weight: bold;"
        else:
            border = current_color("btn_border")
            bw = "1px"
            bg = "transparent"
            self._mark.setText("")
            label_css = f"color: {text}; font-size: 13px;"
        self._label.setStyleSheet(label_css)
        self._desc.setStyleSheet(f"color: {muted}; font-size: 11px;")
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: {bw} solid {border};"
            f" border-radius: 10px; }}"
            f"QPushButton:hover {{ border-color: {accent}; }}")


class InputPreferencesPopover(QWidget):
    """AI 输入栏「偏好」气泡面板:回答方式 / 操作确认 / 文件权限 三项。
    Qt.Popup 浮层(点外部自动关闭),弹出时钳制在屏幕内,不会冲出窗口;
    每行是 OptionCard 卡片,点选即回调(立即生效并保存)。"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(328)
        self._on_select = None        # (group_key, value) -> None
        self._groups = {}             # key -> {"cards": [OptionCard], "value": current}

        # 整个气泡即一个圆角不透明面:外层 widget 自身画圆角背景(无方角),
        # 不透明底 + 无阴影,避免半透明浮层在合成器上渲染出黑边。
        self.setObjectName("InputPreferencesPopover")
        set_style(self, lambda: (
            f"QWidget#InputPreferencesPopover {{"
            f" background: {current_color('bg1')};"
            f" border: 1px solid {current_color('panel_border')};"
            " border-radius: 16px; }"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        title = QLabel("偏好")
        title.setStyleSheet(f"color: {text_color()}; font-size: 13px; font-weight: bold;")
        lay.addWidget(title)

        self._section("response_style", "回答方式", lay)
        self._section("confirmation_mode", "操作确认", lay)
        self._section("permission", "文件权限", lay)

    # ---- 分组构造 ----
    def _section(self, key: str, label: str, lay):
        head = QLabel(label)
        head.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        lay.addSpacing(4)
        lay.addWidget(head)
        cards_lay = QVBoxLayout()
        cards_lay.setSpacing(4)
        lay.addLayout(cards_lay)
        self._groups[key] = {"cards": [], "value": None, "cards_lay": cards_lay}

    def add_option(self, group: str, label: str, value, description: str = ""):
        g = self._groups[group]
        card = OptionCard(label, value, description)
        card.clicked.connect(lambda _c=False, g=group, v=value: self._pick(g, v))
        g["cards"].append(card)
        g["cards_lay"].addWidget(card)

    def set_current(self, group: str, value):
        g = self._groups.get(group)
        if not g:
            return
        g["value"] = value
        for card in g["cards"]:
            card.set_on(card.value == value)

    def current(self, group: str):
        g = self._groups.get(group)
        return g["value"] if g else None

    def set_on_select(self, cb):
        self._on_select = cb

    def _pick(self, group: str, value):
        self.set_current(group, value)
        if self._on_select:
            self._on_select(group, value)

    # ---- 弹出/钳制 ----
    def _apply_round_mask(self):
        """给原生 Popup 窗口套圆角遮罩:仅靠样式 border-radius 只圆了背景填充,
        窗口区域仍是方角,合成器会在外面补出方角边;用 QPainterPath 造圆角 region
        设 mask,让窗口区域本身真正变圆(该 Qt 版本 QRegion 无 RoundRectangle,故手绘)。"""
        from PySide6.QtGui import QPainterPath, QPolygonF, QRegion
        from PySide6.QtCore import QRectF
        w, h = max(1, self.width()), max(1, self.height())
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 16, 16)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_round_mask()

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_round_mask()

    def pop_at(self, global_point):
        """在 global_point(按钮左下)附近弹出,自动翻转并钳制在所在屏幕内。"""
        self.adjustSize()
        w, h = self.width(), self.height()
        px, py = global_point.x(), global_point.y()
        screen = QApplication.screenAt(global_point)
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # 默认在按钮下方左对齐;下方放不下则翻到上方
        x = px
        y = py + 4
        if avail is not None:
            if y + h > avail.bottom() - 6:
                flip = global_point.y() - h - 8   # 挪到按钮上方
                if flip > avail.top() + 6:
                    y = flip
                else:
                    y = max(avail.top() + 6, avail.bottom() - 6 - h)
            x = max(avail.left() + 6, min(x, avail.right() - 6 - w))
        self.move(int(x), int(y))
        self._apply_round_mask()
        self.show()
        self.raise_()


# 思考程度 / 模拟悟程度 档位(Codex 的 reasoning_effort 六档;模型给几档就分几档)
EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh")
EFFORT_LABELS = {
    "none": "无", "minimal": "极轻", "low": "轻",
    "medium": "均衡", "high": "深", "xhigh": "极深",
}


class ModelEffortPopover(QWidget):
    """模型 + 思考程度入口(参考 Codex):上半选模型,下半一条「思考程度」滑条。
    云端模型 = 思考程度;内置本地模型 = 模拟悟程度(同一旋钮,后端各自解读)。
    effort 变化发 effortChanged(str);模型变化发 modelChanged(str)。"""
    effortChanged = Signal(str)
    modelChanged = Signal(str)
    strategyChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(300)
        self.setObjectName("ModelEffortPopover")
        set_style(self, lambda: (
            f"QWidget#ModelEffortPopover {{ background: {current_color('bg1')};"
            f" border: 1px solid {current_color('panel_border')}; border-radius: 14px; }}"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # ---- 模型单选 ----
        mtitle = QLabel("模型")
        mtitle.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        lay.addWidget(mtitle)
        self.model_group = QButtonGroup(self)
        self.model_group.setExclusive(True)
        self._model_rows = {}
        self.model_box = QVBoxLayout()
        self.model_box.setSpacing(4)
        lay.addLayout(self.model_box)

        # ---- 思考程度 / 模拟悟程度 滑条 ----
        self.effort_title = QLabel("思考程度")
        self.effort_title.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        lay.addWidget(self.effort_title)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(EFFORT_LEVELS) - 1)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(1)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(1)
        self.slider.valueChanged.connect(self._on_slider)
        lay.addWidget(self.slider)
        self.effort_value = QLabel("")
        self.effort_value.setStyleSheet(f"color: {text_color()}; font-size: 12px; font-weight: bold;")
        lay.addWidget(self.effort_value)
        self.effort_hint = QLabel("")
        self.effort_hint.setWordWrap(True)
        self.effort_hint.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        lay.addWidget(self.effort_hint)

        # ---- 模型策略(本地优先/云端优先/混合) ----
        stitle = QLabel("模型策略")
        stitle.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        lay.addWidget(stitle)
        self.strategy_group = QButtonGroup(self)
        self.strategy_group.setExclusive(True)
        self._strategy_rows = {}
        self.strategy_box = QVBoxLayout()
        self.strategy_box.setSpacing(4)
        lay.addLayout(self.strategy_box)

    # ---- 模型策略 ----
    def set_strategies(self, items, current: str = None):
        """items: [(key, label)];重建单选行,选中 current。"""
        for rb in list(self._strategy_rows.values()):
            self.strategy_group.removeButton(rb)
            rb.setParent(None)
        self._strategy_rows.clear()
        for key, label in items:
            rb = QRadioButton(label)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            set_style(rb, lambda: (
                f"QRadioButton {{ color: {text_color()}; spacing: 8px; padding: 4px 2px; }}"))
            self.strategy_group.addButton(rb)
            self.strategy_box.addWidget(rb)
            self._strategy_rows[key] = rb
            rb.toggled.connect(lambda on, k=key: on and self.strategyChanged.emit(k))
        if current and current in self._strategy_rows:
            rb = self._strategy_rows[current]
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)

    def current_strategy(self):
        for key, rb in self._strategy_rows.items():
            if rb.isChecked():
                return key
        return None
    def set_models(self, items, current_id: str = None):
        """items: [(model_id, label)];重建单选行,选中 current_id。"""
        for rb in list(self._model_rows.values()):
            self.model_group.removeButton(rb)
            rb.setParent(None)
        self._model_rows.clear()
        for mid, label in items:
            rb = QRadioButton(label)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            set_style(rb, lambda: (
                f"QRadioButton {{ color: {text_color()}; spacing: 8px; padding: 4px 2px; }}"))
            self.model_group.addButton(rb)
            self.model_box.addWidget(rb)
            self._model_rows[mid] = rb
            rb.toggled.connect(lambda on, m=mid: on and self.modelChanged.emit(m))
        if current_id and current_id in self._model_rows:
            rb = self._model_rows[current_id]
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)

    def current_model(self):
        for mid, rb in self._model_rows.items():
            if rb.isChecked():
                return mid
        return None

    # ---- 思考程度 ----
    def set_effort(self, effort: str, is_builtin: bool = False):
        idx = EFFORT_LEVELS.index(effort) if effort in EFFORT_LEVELS else 3
        self.slider.blockSignals(True)
        self.slider.setValue(idx)
        self.slider.blockSignals(False)
        self._is_builtin = is_builtin
        self.effort_title.setText("模拟悟程度" if is_builtin else "思考程度")
        self._refresh_effort_text()

    def _on_slider(self, idx: int):
        effort = EFFORT_LEVELS[max(0, min(idx, len(EFFORT_LEVELS) - 1))]
        self.effortChanged.emit(effort)
        self._refresh_effort_text()

    def _refresh_effort_text(self):
        idx = self.slider.value()
        effort = EFFORT_LEVELS[idx]
        self.effort_value.setText(f"{EFFORT_LABELS[effort]}（{effort}）")
        if getattr(self, "_is_builtin", False):
            # 内置本地模型:模拟悟深度 = 两阶段/自检(1/2/3)
            from local_ai import stage_for_effort
            stage = stage_for_effort(effort)
            hint = {1: "快速:单阶段直取,省时。",
                    2: "均衡:两阶段(先选组再选工具),更准。",
                    3: "深度:两阶段+自检,最稳但更慢。"}.get(stage, "")
            self.effort_hint.setText(f"本地模拟悟阶段 {stage}/3。{hint}")
        else:
            self.effort_hint.setText("越高越慢但更透彻;简单任务用「轻/均衡」即可。")

    # ---- 弹出(复用 InputPreferencesPopover 的钳制逻辑)----
    def _apply_round_mask(self):
        from PySide6.QtGui import QPainterPath, QRegion
        from PySide6.QtCore import QRectF
        w, h = max(1, self.width()), max(1, self.height())
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 14, 14)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_round_mask()

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_round_mask()

    def pop_at(self, global_point):
        self.adjustSize()
        w, h = self.width(), self.height()
        px, py = global_point.x(), global_point.y()
        screen = QApplication.screenAt(global_point) or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        x = px
        y = py + 4
        if avail is not None:
            if y + h > avail.bottom() - 6:
                flip = global_point.y() - h - 8
                if flip > avail.top() + 6:
                    y = flip
                else:
                    y = max(avail.top() + 6, avail.bottom() - 6 - h)
            x = max(avail.left() + 6, min(x, avail.right() - 6 - w))
        self.move(int(x), int(y))
        self._apply_round_mask()
        self.show()
        self.raise_()


class AskUserPanel(QFrame):
    """在聊天输入框上方回答 ask_user，保留多选和自由补充。"""

    submitted = Signal(list)
    canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AskUserPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#AskUserPanel {{ border: 1px solid {muted_color()};"
            f" border-radius: 8px; background: {current_color('panel_bg')}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        self.question_label = QLabel()
        self.question_label.setWordWrap(True)
        layout.addWidget(self.question_label)
        self.options_layout = QVBoxLayout()
        layout.addLayout(self.options_layout)
        self.checks = []
        self.input = QLineEdit()
        self.input.setPlaceholderText("选项不够？可以补充说明")
        self.input.returnPressed.connect(self._submit)
        layout.addWidget(self.input)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.canceled.emit)
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self._submit)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)
        self.hide()

    def show_question(self, question: str, options: list):
        self.question_label.setText(question or "你想要哪个？")
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.checks = [QCheckBox(str(option)) for option in (options or [])]
        for check in self.checks:
            self.options_layout.addWidget(check)
        self.input.clear()
        self.show()
        self.input.setFocus()

    def _submit(self):
        picked = [check.text() for check in self.checks if check.isChecked()]
        extra = self.input.text().strip()
        if extra:
            picked.append(extra)
        self.submitted.emit(picked)


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
    preferencesClicked = Signal()
    modelEffortClicked = Signal()   # 模型 + 思考程度入口(发送键左边)
    imagePasted = Signal(QImage)   # 从剪贴板粘贴了图片

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMaximumHeight(160)
        # 发送按钮缩小居中,外圈环绕上下文占用环(与下载指示器同款表示)
        self.send_btn = SendWithRing(self)
        self.send_btn.setToolTip("发送(Enter)")
        self.send_btn.clicked.connect(self.sendClicked.emit)
        # 模型 + 思考程度入口(发送键左边,参考 Codex):点开弹出选模型/调思考(内置=模拟悟)
        self.model_btn = QPushButton("模型", self)
        self.model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_btn.setToolTip("选择模型 / 调思考程度(内置模型=模拟悟程度)")
        self.model_btn.clicked.connect(self.modelEffortClicked.emit)
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
        # 「偏好/权限」:左下角半透明胶囊按钮,点开回答方式/操作确认/文件权限面板
        self.preferences_btn = QPushButton("偏好/权限", self)
        self.preferences_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preferences_btn.setToolTip("回答方式 / 操作确认 / 文件权限")
        self.preferences_btn.clicked.connect(self.preferencesClicked.emit)
        # 文字跟随主题:浅色模式黑色、深色模式白色(半透明灰底上都能看清)
        set_style(self.preferences_btn, lambda:
            f"QPushButton {{ color: {text_color()}; background: rgba(128,128,128,70);"
            " border: none; border-radius: 12px; padding: 3px 12px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(128,128,128,130); }")
        # 右下角按钮(从右到左):发送环 → 模型 → 🛠 → 📷 → 🖼 → 🎤
        # 布局 loop 用 reversed() 从右往左摆,故列表尾部=最右;send 放尾(最右),model 次右(发送键左边)。
        # 📷/🖼 是图片相关按钮,模型不支持多模态时隐藏(见 set_vision_enabled)
        self._corner_btns = [self.test_btn, self.img_btn, self.recent_btn,
                             self.voice_btn, self.model_btn, self.send_btn]
        for button in self._corner_btns[:4]:   # 🛠📷🖼🎤 是圆形图标钮(非 send/model 胶囊)
            button.setFixedSize(22, 22)
            button.setStyleSheet(
                "QPushButton { border-radius:11px; background:rgba(128,128,128,90);"
                " font-size:12px; border:none; padding:0px; min-width:0px; min-height:0px; }"
                "QPushButton:hover { background:rgba(128,128,128,160); }")
        # 模型入口是文字胶囊(不是圆钮),样式同「偏好/权限」
        set_style(self.model_btn, lambda:
            f"QPushButton {{ color: {text_color()}; background: rgba(128,128,128,70);"
            " border: none; border-radius: 12px; padding: 3px 12px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(128,128,128,130); }")
        self.model_btn.setFixedHeight(22)
        self.model_btn.adjustSize()
        self.preferences_btn.setFixedHeight(22)
        self.preferences_btn.adjustSize()
        self.setViewportMargins(0, 0, 0, 38)
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
        """右下角圆形按钮从右到左摆放(只排可见的);「偏好/权限」固定在左下角。"""
        if self.width() <= 0 or self.height() <= 0:
            return   # 尺寸未就绪(启动时)不摆,等 showEvent/resizeEvent
        m = 6
        x = self.width() - m
        for b in reversed(self._corner_btns):
            if not b.isVisible():
                continue
            x -= b.width() + m
            b.move(x, self.height() - b.height() - m)
        # 左下角:偏好/权限
        pb = self.preferences_btn
        pb.move(m, self.height() - pb.height() - m)

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

    def contextMenuEvent(self, event):
        """覆盖 QPlainTextEdit 默认英文右键菜单,提供中文编辑菜单并跟随主题。"""
        menu = QMenu(self)
        menu.setStyleSheet(popup_menu_style())

        undo_action = QAction("撤销", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.setEnabled(self.document().isUndoAvailable())
        undo_action.triggered.connect(self.undo)
        menu.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.setShortcut("Ctrl+Y")
        redo_action.setEnabled(self.document().isRedoAvailable())
        redo_action.triggered.connect(self.redo)
        menu.addAction(redo_action)

        menu.addSeparator()

        cursor = self.textCursor()
        has_selection = cursor.hasSelection()

        cut_action = QAction("剪切", self)
        cut_action.setShortcut("Ctrl+X")
        cut_action.setEnabled(has_selection)
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)

        copy_action = QAction("复制", self)
        copy_action.setShortcut("Ctrl+C")
        copy_action.setEnabled(has_selection)
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        paste_action = QAction("粘贴", self)
        paste_action.setShortcut("Ctrl+V")
        paste_action.setEnabled(self.canPaste())
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        delete_action = QAction("删除", self)
        delete_action.setEnabled(has_selection)
        delete_action.triggered.connect(self._delete_selected_text)
        menu.addAction(delete_action)

        menu.addSeparator()

        select_all_action = QAction("全选", self)
        select_all_action.setShortcut("Ctrl+A")
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.exec(event.globalPos())

    def _delete_selected_text(self):
        cursor = self.textCursor()
        cursor.removeSelectedText()
        self.setTextCursor(cursor)
