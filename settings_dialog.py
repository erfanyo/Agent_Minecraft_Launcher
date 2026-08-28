# -*- coding: utf-8 -*-
"""
设置对话框(启动器整体设置),按功能拆成多个标签页:
- 游戏:游戏名、内存、版本隔离、游戏目录(.minecraft 位置,可指向任意已有目录)
- 界面:语言、界面模式
- AI 助手:服务商 / 接口 / 密钥 / 模型 / 文件权限 / 多模态(图片输入)
- 镜像源:选择下载镜像源(官方 / BMCLAPI / 自定义),管理自定义镜像
点"确定"时把各标签页内容写进 config.json。

AI 助手页另含「下载本地模型」按钮:主动点击触发后台下载(镜像优先),进度同步到
启动器左下角环形下载指示器,按钮三态(未下载/下载中/已就绪)。
"""
import threading
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
)

import i18n
from i18n import t
import paths
from assistant import AISettingsForm
from downloader import MIRROR_SOURCES, MIRROR_STRATEGIES
from settings import save_settings
from ui_style import card_btn_style, muted_color, set_style


class SettingsDialog(QDialog):
    # 下载进度/结果从 worker 线程搬回主线程更新 UI(跨线程安全)
    _dl_progress = Signal(int, int)      # (done, total)
    _dl_finished = Signal(bool, str)     # (ok, message)

    def __init__(self, settings: dict, parent=None, tab: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("启动器设置")
        self.setMinimumWidth(470)
        self.settings = dict(settings)  # 复制一份,点确定才真正生效
        self._custom_mirrors = [dict(c) for c in self.settings.get("custom_mirrors", []) or []]

        self._model_downloading = False        # 本地模型是否正在下载
        self._mod_translate_check = None       # 惰性创建,见 AI tab
        # 下载信号:worker 线程 emit → 主线程槽(用 QueuedConnection 保证线程安全)
        self._dl_progress.connect(self._on_model_dl_progress)
        self._dl_finished.connect(self._on_model_dl_finished)

        # ---------- 标签页:游戏 / 界面 / AI 助手 / 镜像源 ----------
        self.tabs = QTabWidget()
        self.tabs.addTab(self._wrap_scroll(self._build_game_tab()), "游戏")
        self.tabs.addTab(self._wrap_scroll(self._build_ui_tab()), "界面")
        self.tabs.addTab(self._wrap_scroll(self._build_ai_tab()), "AI 助手")
        self.tabs.addTab(self._wrap_scroll(self._build_mirror_tab()), "镜像源")
        if tab == "mirror":
            self.tabs.setCurrentIndex(self.tabs.count() - 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

    def _wrap_scroll(self, content: QWidget) -> QWidget:
        """把标签页内容包进一个可滚动区域:内容高过窗口时出现滚轮,不再被裁剪/重叠。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    # ================= 游戏 =================
    def _build_game_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 16)
        self.memory_spin.setSuffix(" GB")
        self.memory_spin.setValue(self.settings.get("memory_gb", 2))

        self.isolation_check = QCheckBox("每个版本用独立游戏目录(存档/配置/Mod 互不干扰)")
        self.isolation_check.setChecked(self.settings.get("version_isolation", True))

        self.game_dir_edit = QLineEdit(self.settings.get("game_dir") or paths.DEFAULT_GAME_DIR)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_game_dir)
        default_btn = QPushButton("默认")
        default_btn.setToolTip("回到启动器目录下的 .minecraft")
        default_btn.clicked.connect(lambda: self.game_dir_edit.setText(paths.DEFAULT_GAME_DIR))
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.game_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        dir_row.addWidget(default_btn)

        form = QFormLayout()
        form.addRow("内存:", self.memory_spin)
        form.addRow("版本隔离:", self.isolation_check)
        form.addRow("游戏目录:", dir_row)
        dir_hint = QLabel("可以是任意位置,包括 PCL2 / 官方启动器创建的 .minecraft(自动读取里面的实例)")
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet(f"color: {muted_color()};")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(dir_hint)
        lay.addStretch()
        return w

    def _browse_game_dir(self):
        start = self.game_dir_edit.text().strip() or paths.DEFAULT_GAME_DIR
        d = QFileDialog.getExistingDirectory(self, "选择 Minecraft 游戏目录", start)
        if d:
            self.game_dir_edit.setText(d)

    # ================= 界面 =================
    def _build_ui_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        # 界面语言(自动跟随系统,可覆盖)
        self.language_combo = QComboBox()
        for label, value in (("自动(跟随系统)", "auto"), ("中文", "zh"), ("English", "en")):
            self.language_combo.addItem(label, value)
        cur = self.settings.get("language", "auto")
        idx = self.language_combo.findData(cur)
        self.language_combo.setCurrentIndex(idx if idx >= 0 else 0)
        lang_hint = QLabel("切换语言后需重启启动器生效(检测系统语言:中文系统自动用中文)")
        lang_hint.setStyleSheet(f"color: {muted_color()};")

        # 界面模式(全面:多提示/科普;摘要:精简) —— 对外叫「全面 / 摘要」,
        # 不用「新手 / 专家」(免得显得看不起新手)。值保持 beginner/expert 兼容旧配置。
        self.ui_mode_combo = QComboBox()
        for label, value in ((t("FULL_MORE_TIPS_GUIDES"), "beginner"),
                             (t("SUMMARY_CONCISE"), "expert")):
            self.ui_mode_combo.addItem(label, value)
        mode = self.settings.get("ui_mode", "beginner")
        idx = self.ui_mode_combo.findData(mode)
        self.ui_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        mode_hint = QLabel(t("FULL_SHOWS_RESOURCE_GUIDE_DETAILED_HINTS_SUMMARY_HIDES_THEM_CONCISE"))
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet(f"color: {muted_color()};")
        mode_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("界面语言:", self.language_combo)
        form.addRow("界面模式:", self.ui_mode_combo)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(lang_hint)
        lay.addWidget(mode_hint)
        lay.addSpacing(10)
        # ---- 已临时弃用 / 废案(未移除)功能:隐藏主入口,在此登记(见 deprecated_features.py) ----
        from deprecated_features import get_deprecated
        dep = get_deprecated()
        if dep:
            dep_title = QLabel("⚠️ 已临时弃用 / 废案(未移除)功能:")
            dep_title.setStyleSheet(f"color: {muted_color()}; font-weight: bold;")
            lay.addWidget(dep_title)
            for d in dep:
                row = QHBoxLayout()
                info = QLabel(f"<b>{d.get('name')}</b>  ·  状态:{d.get('status','')}<br>"
                              f"<span style='color:{muted_color()};'>{d.get('note','')}</span>")
                info.setWordWrap(True)
                info.setTextFormat(Qt.TextFormat.RichText)
                row.addWidget(info, 1)
                if d.get("reopen") == "tutorial":
                    open_btn = QPushButton("临时查看")
                    set_style(open_btn, card_btn_style)
                    open_btn.clicked.connect(self._reopen_tutorial)
                    row.addWidget(open_btn)
                lay.addLayout(row)
        lay.addStretch()
        return w

    def _reopen_tutorial(self):
        """设置里「临时查看」已弃用的新手教程(主入口已隐藏,仅此保留访问)。"""
        p = self.parent()
        if p is not None and hasattr(p, "open_tutorial"):
            p.open_tutorial()

    # ================= AI 助手 =================
    def _build_ai_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        self.ai_form = AISettingsForm(self.settings)
        ai_hint = QLabel("AI 设置会自动保存,下次打开启动器仍然有效。\n"
                         "· 云/本地两块分开配:顶部选「当前使用(AI 策略)」哪档,AI 对话就走哪边;\n"
                         "· ⚠️ 本地是小模型:只懂直白指令,理解不了模糊需求(如\"按功能找 mod\"),甚至会选错工具;"
                         "这类要靠云端,想要稳定体验请配云端(如 DeepSeek);\n"
                         "· 发图片(多模态):只有所选模型本身会\"看图\"才有效,内置本地模型自动关闭;\n"
                         "· 本地模型约 500MB,首次用到时后台自动下载(镜像优先)。")
        ai_hint.setWordWrap(True)
        ai_hint.setStyleSheet(f"color: {muted_color()};")

        # Mod 描述本地 AI 翻译(英→中)开关:归属 AI 功能,默认开
        self.mod_translate_check = QCheckBox("Mod 描述本地 AI 翻译(英→中)")
        self.mod_translate_check.setChecked(bool(self.settings.get("ai_mod_translate", True)))
        self.mod_translate_check.setToolTip(
            "在「下载新资源 → 资源详情」面板把英文 Mod 描述翻译成中文。\n"
            "开:详情显示中文翻译 + \"机翻仅供参考\"标注;关:显示英文原文。")
        mod_ai_hint = QLabel("开:选 Mod 时详情面板把英文描述翻成中文(本地小模型,翻译在后台跑,不卡界面)。")
        mod_ai_hint.setWordWrap(True)
        mod_ai_hint.setStyleSheet(f"color: {muted_color()};")
        mod_ai_row = QHBoxLayout()
        mod_ai_row.addWidget(self.mod_translate_check)
        mod_ai_row.addStretch()

        # 下载本地模型按钮(三态):主动点击触发后台下载,进度同步到左下角环形指示器
        self.model_dl_btn = QPushButton(t("DOWNLOAD_LOCAL_MODEL"))
        self.model_dl_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_dl_btn.clicked.connect(self._start_model_download)
        self.model_dl_status = QLabel("")
        self.model_dl_status.setWordWrap(True)
        self.model_dl_status.setStyleSheet(f"color: {muted_color()};")
        model_dl_row = QHBoxLayout()
        model_dl_row.addWidget(self.model_dl_btn)
        model_dl_row.addWidget(self.model_dl_status, 1)
        self._init_model_dl_button()

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.ai_form)
        lay.addLayout(mod_ai_row)
        lay.addWidget(mod_ai_hint)
        lay.addLayout(model_dl_row)
        lay.addWidget(ai_hint)
        lay.addStretch()
        return w

    # ================= 镜像源 =================
    def _build_mirror_tab(self) -> QWidget:
        from PySide6.QtWidgets import QWidget

        # 下载策略:官方/镜像谁优先、用不用(官方源与镜像站的分工由策略决定)
        self.strategy_combo = QComboBox()
        for key, info in MIRROR_STRATEGIES.items():
            self.strategy_combo.addItem(info["name"], key)
        cur = self.settings.get("mirror_strategy", "smart_official")
        idx = self.strategy_combo.findData(cur)
        self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        self.strategy_hint = QLabel("")
        self.strategy_hint.setWordWrap(True)
        self.strategy_hint.setStyleSheet(f"color: {muted_color()};")
        self._update_strategy_hint()

        # 镜像站:实际用到的镜像(策略里"只用官方"时自动禁用)
        self.mirror_hint = QLabel("")
        self.mirror_hint.setWordWrap(True)
        self.mirror_hint.setStyleSheet(f"color: {muted_color()};")
        self.mirror_combo = QComboBox()
        self._refresh_mirror_combo()
        self.mirror_combo.currentIndexChanged.connect(self._update_mirror_hint)
        self.mirror_combo.setEnabled(cur != "official_only")

        form = QFormLayout()
        form.addRow("下载策略:", self.strategy_combo)
        form.addRow("", self.strategy_hint)
        form.addRow("镜像站:", self.mirror_combo)
        form.addRow("", self.mirror_hint)

        # 自定义镜像:名称 + 地址,添加进列表;选中可删除
        self.custom_name_edit = QLineEdit()
        self.custom_name_edit.setPlaceholderText("名称,如 我的镜像")
        self.custom_url_edit = QLineEdit()
        self.custom_url_edit.setPlaceholderText("base 地址,如 https://mirror.example.com")
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._add_custom_mirror)
        add_row = QHBoxLayout()
        add_row.addWidget(self.custom_name_edit, 1)
        add_row.addWidget(self.custom_url_edit, 2)
        add_row.addWidget(add_btn)

        self.custom_list = QListWidget()
        self.custom_list.setMinimumHeight(90)
        self._refresh_custom_list()
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._remove_custom_mirror)
        del_row = QHBoxLayout()
        del_row.addStretch()
        del_row.addWidget(del_btn)

        sep = QLabel("自定义镜像(与 BMCLAPI 同构:填 base 地址,自动映射 libraries/ assets/ version/ 等路径)")
        sep.setWordWrap(True)
        sep.setStyleSheet("font-weight: bold; margin-top: 10px;")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(form)
        lay.addWidget(sep)
        lay.addLayout(add_row)
        lay.addWidget(self.custom_list)
        lay.addLayout(del_row)
        lay.addStretch()
        return w

    def _on_strategy_changed(self):
        self._update_strategy_hint()
        # "只用官方源"时镜像站用不上,禁用选择框
        self.mirror_combo.setEnabled(self.strategy_combo.currentData() != "official_only")

    def _update_strategy_hint(self):
        key = self.strategy_combo.currentData()
        info = MIRROR_STRATEGIES.get(key)
        self.strategy_hint.setText(info["desc"] if info else "")

    def _refresh_mirror_combo(self):
        """重建镜像源下拉框(内置预设 + 自定义),尽量保持原选中项"""
        cur = self.mirror_combo.currentData() if self.mirror_combo.count() \
            else self.settings.get("mirror_source", "bmclapi")
        self.mirror_combo.blockSignals(True)
        self.mirror_combo.clear()
        for key, info in MIRROR_SOURCES.items():
            self.mirror_combo.addItem(info["name"], key)
        for cm in self._custom_mirrors:
            self.mirror_combo.addItem(f"自定义: {cm.get('name', '?')}", "custom:" + cm.get("id", ""))
        idx = self.mirror_combo.findData(cur)
        if idx < 0:   # 原选中项已被删除(如自定义镜像被移除)→ 退回 BMCLAPI
            idx = self.mirror_combo.findData("bmclapi")
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mirror_combo.blockSignals(False)
        self._update_mirror_hint()

    def _update_mirror_hint(self):
        key = self.mirror_combo.currentData()
        if key in MIRROR_SOURCES:
            self.mirror_hint.setText(MIRROR_SOURCES[key]["desc"])
        elif key and key.startswith("custom:"):
            cid = key.split(":", 1)[1]
            for cm in self._custom_mirrors:
                if cm.get("id") == cid:
                    self.mirror_hint.setText(f"自定义镜像:{cm.get('name', '')} — {cm.get('url', '')}")
                    return
            self.mirror_hint.setText("自定义镜像")
        else:
            self.mirror_hint.setText("")

    def _add_custom_mirror(self):
        name = self.custom_name_edit.text().strip()
        url = self.custom_url_edit.text().strip()
        if not name or not url:
            QMessageBox.warning(self, "镜像源", "请填写名称和地址")
            return
        if not url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "镜像源", "地址必须以 http:// 或 https:// 开头")
            return
        self._custom_mirrors.append(
            {"id": uuid.uuid4().hex[:8], "name": name, "url": url.rstrip("/")})
        self.custom_name_edit.clear()
        self.custom_url_edit.clear()
        self._refresh_custom_list()
        self._refresh_mirror_combo()
        # 选中刚添加的自定义镜像
        idx = self.mirror_combo.findData("custom:" + self._custom_mirrors[-1]["id"])
        self.mirror_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _refresh_custom_list(self):
        self.custom_list.clear()
        for cm in self._custom_mirrors:
            self.custom_list.addItem(f"{cm.get('name', '?')}  —  {cm.get('url', '')}")

    def _remove_custom_mirror(self):
        row = self.custom_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "镜像源", "先在列表里选中要删除的自定义镜像")
            return
        self._custom_mirrors.pop(row)
        self._refresh_custom_list()
        self._refresh_mirror_combo()   # 若正在用被删的镜像,自动退回 BMCLAPI

    # ================= 确定 =================
    def accept(self):
        """点确定:把各标签页内容收集进 self.settings 并保存"""
        self.settings["memory_gb"] = self.memory_spin.value()
        self.settings["version_isolation"] = self.isolation_check.isChecked()
        self.settings["game_dir"] = self.game_dir_edit.text().strip()
        self.settings["language"] = self.language_combo.currentData()
        self.settings["ui_mode"] = self.ui_mode_combo.currentData()
        self.settings.update(self.ai_form.values())   # 含 ai_strategy/ai_source/ai_multimodal(多模态图片输入)
        self.settings["ai_mod_translate"] = self.mod_translate_check.isChecked()
        self.settings["mirror_strategy"] = self.strategy_combo.currentData()
        self.settings["mirror_source"] = self.mirror_combo.currentData()
        self.settings["custom_mirrors"] = self._custom_mirrors
        save_settings(self.settings)
        i18n.set_language(self.settings["language"])
        paths.set_game_dir(self.settings["game_dir"])  # 改路径立即全局生效
        super().accept()

    # ================= 下载本地模型(主动点击,进度同步到环形指示器) =================
    def _is_model_downloaded(self) -> bool:
        """内置本地模型是否已下载。"""
        try:
            import model_registry
            return model_registry.is_downloaded("qwen3.5-0.8b-xlam-q4km")
        except Exception:
            return False

    def _init_model_dl_button(self):
        """根据当前下载状态初始化按钮三态。"""
        ready = self._is_model_downloaded()
        if ready:
            self.model_dl_btn.setText(t("READY"))
            self.model_dl_btn.setEnabled(False)
            self.model_dl_status.setText(t("LOCAL_MODEL_DOWNLOADED_READY"))
        else:
            self.model_dl_btn.setText(t("DOWNLOAD_LOCAL_MODEL"))
            self.model_dl_btn.setEnabled(True)
            self.model_dl_status.setText(t("NOT_DOWNLOADED_500MB_CLICK_TO_START"))

    def _start_model_download(self):
        """点击「下载本地模型」:后台线程下载(镜像优先),进度同步到左下角环形指示器。"""
        if self._model_downloading:
            return   # 下载中再点无效
        if self._is_model_downloaded():
            self._init_model_dl_button()
            return
        self._model_downloading = True
        self.model_dl_btn.setEnabled(False)
        self.model_dl_btn.setText(t("DOWNLOADING_0"))
        self.model_dl_status.setText(t("DOWNLOADING_LOCAL_MODEL_MIRROR_FIRST"))

        # 左下角环形指示器开始读条(优先经宿主 MainWindow 写日志,详情对话框可见进度)
        host = self.parent()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("正在下载本地模型(约500MB,镜像优先)…", 0, 1)
        else:
            ring = getattr(host, "dl_indicator", None) if host else None
            if ring is not None:
                ring.set_progress(0, 1)
                ring.setToolTip("正在下载本地模型,点击查看详情")
                ring.show()

        def worker():
            ok, msg = True, "✅ 本地模型下载完成,之后可用内置本地模型。"
            try:
                import model_registry
                model_registry.download(
                    "qwen3.5-0.8b-xlam-q4km",
                    progress_callback=lambda d, t: self._dl_progress.emit(d, t))
            except Exception as e:
                ok = False
                msg = f"❌ 本地模型下载失败:{type(e).__name__}: {str(e)[:200]}(可稍后重新触发)"
            self._dl_finished.emit(ok, msg)

        threading.Thread(target=worker, daemon=True).start()

    def _on_model_dl_progress(self, done, total):
        """主线程:更新按钮百分比 + 环形指示器进度(并写入主窗口下载日志/详情)。"""
        pct = int(done * 100 / total) if total else 0
        self.model_dl_btn.setText(t(f"下载中 {pct}%…", f"Downloading {pct}%…"))
        host = self.parent()
        if host is not None and hasattr(host, "model_download_progress"):
            host.model_download_progress("", done, total)
        else:
            ring = getattr(host, "dl_indicator", None) if host else None
            if ring is not None:
                ring.set_progress(done, total)

    def _on_model_dl_finished(self, ok, msg):
        """主线程:下载结束,恢复按钮状态 + 提示 + 停环形指示器(并写主窗口下载日志)。"""
        self._model_downloading = False
        self.model_dl_status.setText(msg)
        host = self.parent()
        if host is not None and hasattr(host, "model_download_done"):
            host.model_download_done(ok, msg)
        else:
            ring = getattr(host, "dl_indicator", None) if host else None
            if ring is not None:
                ring.set_progress(1, 1)
                ring.setToolTip("本地模型下载" + ("完成,点击查看详情" if ok else "失败,点击查看详情"))
                from PySide6.QtCore import QTimer
                QTimer.singleShot(2000, ring.hide)
        if ok:
            self.model_dl_btn.setText(t("READY"))
            self.model_dl_btn.setEnabled(False)
        else:
            # 失败 → 可重试
            self.model_dl_btn.setText(t("DOWNLOAD_LOCAL_MODEL"))
            self.model_dl_btn.setEnabled(True)
