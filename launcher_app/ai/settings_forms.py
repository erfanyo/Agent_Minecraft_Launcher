"""Assistant settings widgets and model selection controls.

Provider/default data belongs to assistant_defaults; execution is elsewhere.
"""
from launcher_app.core.i18n import t
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QComboBox, QCompleter, QDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListView,
    QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)
from launcher_app.ai.ai_actions import PERMISSIONS
from launcher_app.ai.assistant_defaults import LOCAL_MODEL_ID, _CLOUD_PROVIDERS, _LOCAL_MODES
from launcher_app.ai.assistant_ui import model_supports_vision
from launcher_app.ui.ui_style import set_style, muted_color, text_color
from launcher_app.ui.ui_switch import ToggleSwitch, setting_switch_row

def _limit_combo_popup(combo, visible: int = 10) -> None:
    """限制下拉弹层的可见项数。

    Windows 原生弹层会无视 setMaxVisibleItems(模型可能有几百个,弹层会顶住屏幕上下边框),
    所以换成 Qt 自己的弹层(combobox-popup: 0)并限高,超出部分滚动。
    """
    combo.setView(QListView(combo))
    combo.setMaxVisibleItems(int(visible))
    combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
    view = combo.view()
    if view is not None:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

def _commit_combo_search(combo) -> None:
    """打字后回车:选中匹配项(精确优先,其次包含),避免留下识别不了的自由文本。"""
    text = (combo.currentText() or "").strip().lower()
    if not text:
        return
    best = -1
    for i in range(combo.count()):
        if (combo.itemText(i) or "").strip().lower() == text:
            best = i
            break
    if best < 0:
        for i in range(combo.count()):
            if combo.itemData(i) and text in (combo.itemText(i) or "").lower():
                best = i
                break
    if best >= 0:
        combo.setCurrentIndex(best)
        combo.activated.emit(best)

def _setup_model_combo(combo, placeholder: str) -> None:
    """「获取可用模型」下拉 = 限高(最多 10 行) + 可直接打字搜索。

    模型可能有几百个:光靠滚动不好找,所以把下拉设为可编辑并挂 QCompleter,
    在输入框里打几个字就按「包含」过滤候选。
    """
    _limit_combo_popup(combo)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    if combo.lineEdit() is not None:
        combo.lineEdit().setPlaceholderText(placeholder)
        combo.lineEdit().returnPressed.connect(lambda c=combo: _commit_combo_search(c))
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    popup = completer.popup()
    if popup is not None:
        popup.setMaximumHeight(280)
    combo.setCompleter(completer)
    combo._amcl_completer = completer

def _refresh_model_combo_search(combo) -> None:
    """模型列表被重新填充后,让补全器跟着新内容走。"""
    completer = getattr(combo, "_amcl_completer", None)
    if completer is not None:
        completer.setModel(combo.model())

class AISettingsForm(QWidget):
    """AI 模型设置(拆分云端 / 本地两大块)。

    - 顶部「当前使用」:AI 策略三档(本地优先 / 云端优先 / 混合)——决定 AI 对话走哪边,
      同时决定上方显示云端还是本地配置块(混合两者都显示)。
    - 云端块:服务商(DeepSeek/OpenRouter/硅基流动/智谱/通义/自定义)+ 接口地址 + API 密钥 + 模型。
    - 本地块:本地类型(内置 / Ollama / LM Studio)+
      内置:模型下载状态 + 自动下载;Ollama/LM Studio:服务地址 + 模型名。
    - 通用:文件权限、上下文窗口、图片输入(按模型自动)、游戏内 AI 通道。

    保存时据当前策略/来源推导「生效」的 ai_provider / ai_base_url / ai_api_key / ai_model,
    以及 ai_strategy / ai_source,后端(chat/task_router/local 路由)读到的是统一的一套。
    """

    # AI 策略三档:值 → (文案, 生效来源 cloud/local, 是否两边都显示)
    _STRATEGIES = [
        ("local_first", "本地优先", "local", False),
        ("cloud_first", "云端优先", "cloud", False),
        ("hybrid", "混合", "cloud", True),
    ]

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._provider_keys = dict(settings.get('ai_cloud_api_keys') or {})
        self._key_provider = None
        self._build_ui()
        self._sync_from_settings()
        self._apply_source_visibility()

    @staticmethod
    def _collapsible_group(title: str, content: QWidget, expanded: bool = True) -> tuple[QGroupBox, QToolButton]:
        """轻量折叠组：不用二级菜单，保留常用设置的原位置。"""
        box = QGroupBox()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 5, 8, 7)
        layout.setSpacing(4)
        toggle = QToolButton()
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setStyleSheet("QToolButton { font-weight: bold; border: none; padding: 2px; text-align: left; }")
        content.setVisible(expanded)

        def on_toggle(opened: bool):
            content.setVisible(opened)
            toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)

        toggle.toggled.connect(on_toggle)
        layout.addWidget(toggle)
        layout.addWidget(content)
        return box, toggle

    @staticmethod
    def _set_section_open(toggle: QToolButton, opened: bool):
        if toggle.isChecked() != opened:
            toggle.setChecked(opened)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        """带主题色的小节标题标签(适配深/浅色,避免白底白字看不清)。"""
        lab = QLabel(text)
        set_style(lab, lambda: f"color:{text_color()}; font-weight:bold;")
        return lab

    def _build_ui(self):
        # ---------- 模型类型:顶部二选一(API / 内置)——决定下面显示哪块配置 ----------
        self.model_type_combo = QComboBox()
        self.model_type_combo.addItem("API", "api")
        self.model_type_combo.addItem(t('内置'), "builtin")
        self.model_type_combo.setToolTip(
            t('选「API」→ 配置在线/自建 API 服务(DeepSeek、Ollama、LM Studio、自定义等);\n选「内置」→ 用启动器自带的本地小模型(离线,首次需下载)。'))
        self.model_type_combo.currentIndexChanged.connect(self._apply_source_visibility)

        # ---------- 当前使用(AI 策略三档,合并了原"云端/本地"单选) ----------
        self.strategy_combo = QComboBox()
        for _key, label, _src, _both in self._STRATEGIES:
            self.strategy_combo.addItem(t(label), _key)
        self.strategy_combo.setToolTip(
            t('决定 AI 对话默认怎么分流:\n· 本地优先(省钱):简单操作用本地小模型,复杂任务自动转云端;\n· 云端优先(更强):一切走云端大模型(需联网,未配云端会自动降级);\n· 混合(平衡):按规则分流 + 模型复核,本地/云端平衡。\n⚠️ 本地小模型理解不了模糊/抽象需求(如"按功能找 mod"),这类默认要靠云端;想要稳定的"想装什么就找到"体验建议用「云端优先/混合」。'))
        self.strategy_combo.currentIndexChanged.connect(self._apply_source_visibility)

        # ---------- 云端块 ----------
        self.cloud_provider = QComboBox()
        for label, value in _CLOUD_PROVIDERS:
            self.cloud_provider.addItem(t(label), value)
        self.cloud_base_url = QLineEdit()
        self.cloud_base_url.setPlaceholderText(t('如 https://api.deepseek.com/v1'))
        self.cloud_api_key = QLineEdit()
        self.cloud_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.cloud_api_key.setPlaceholderText("")
        self.cloud_model = QLineEdit()
        self.cloud_model.setPlaceholderText(t('如 deepseek-chat / glm-4.7-flash'))
        cloud_content = QWidget()
        cl = QFormLayout(cloud_content)
        cl.addRow(t('服务商:'), self.cloud_provider)
        cl.addRow(t('接口地址:'), self.cloud_base_url)
        cl.addRow(t('API 密钥:'), self.cloud_api_key)
        model_row = QHBoxLayout()
        model_row.addWidget(self.cloud_model, 1)
        self.fetch_models_btn = QPushButton(t('获取模型'))
        self.fetch_models_btn.setToolTip(t('使用当前地址和密钥查询 /models，不发送推理请求'))
        self.fetch_models_btn.clicked.connect(self._fetch_cloud_models)
        model_row.addWidget(self.fetch_models_btn)
        cl.addRow(t('模型:'), model_row)
        self.remote_models = QComboBox()
        _setup_model_combo(self.remote_models, t('选择模型（列表不保证全部可调用）'))   # 限高 + 可打字搜索
        self.remote_models.hide()
        self.remote_models.activated.connect(self._choose_remote_model)
        cl.addRow('', self.remote_models)
        self.cloud_base_url.textChanged.connect(self.remote_models.hide)
        self.cloud_api_key.textChanged.connect(self.remote_models.hide)
        cloud_box, self._cloud_toggle = self._collapsible_group(t('云端模型'), cloud_content, True)

        # ---------- 本地块 ----------
        self.local_mode = QComboBox()
        for label, value in _LOCAL_MODES:
            self.local_mode.addItem(t(label), value)
        # 内置模型专属:下载状态 + 手动下载按钮(打包已含权重,不再自动下载)
        self.local_builtin_row = QWidget()
        b_row = QHBoxLayout(self.local_builtin_row)
        b_row.setContentsMargins(0, 0, 0, 0)
        self.local_status = QLabel("")
        self.local_dl_btn = QPushButton(t('下载模型'))
        self.local_dl_btn.setToolTip(t('手动下载内置本地模型(约 500MB)。发行包已含权重,一般无需下载。'))
        self.local_dl_btn.clicked.connect(self._manual_download_local_model)
        b_row.addWidget(self.local_status, 1)
        b_row.addWidget(self.local_dl_btn)
        # Ollama / LM Studio 专属:服务地址 + 模型名
        self.local_server_row = QWidget()
        s_form = QFormLayout(self.local_server_row)
        s_form.setContentsMargins(0, 0, 0, 0)
        self.local_endpoint = QLineEdit()
        self.local_endpoint.setPlaceholderText(t('如 http://localhost:11434/v1'))
        self.local_model = QLineEdit()
        self.local_model.setPlaceholderText(t('本机加载的模型名,如 qwen2.5:7b'))
        s_form.addRow(t('服务地址:'), self.local_endpoint)
        s_form.addRow(t('模型名:'), self.local_model)
        local_content = QWidget()
        ll = QVBoxLayout(local_content)
        ll.addWidget(self._section_label(t('本地类型:')))
        ll.addWidget(self.local_mode)
        ll.addWidget(self.local_builtin_row)
        ll.addWidget(self.local_server_row)
        self.local_explainer = QLabel(t('适合离线、基础问答和直白操作；模糊推荐、多步规划建议用云端。'))
        self.local_explainer.setWordWrap(True)
        self.local_explainer.setStyleSheet(f"color: {muted_color()};")
        ll.addWidget(self.local_explainer)
        local_box, self._local_toggle = self._collapsible_group(t('本地模型'), local_content, False)

        # ---------- 通用 ----------
        self.permission = QComboBox()
        for label, value in PERMISSIONS:
            self.permission.addItem(t(label), value)
        from launcher_app.ui.numeric_input import SettingsSpinBox
        self.context_window = SettingsSpinBox()
        self.context_window.setRange(1000, 1000000)
        self.context_window.setSingleStep(1024)
        self.context_window.setSuffix(" tokens")
        self.context_window.setToolTip(t('模型上下文窗口上限,用于对话框里的占用圆环显示'))
        self.vision_check = ToggleSwitch(False)
        self.vision_check.setToolTip(
            t('图片功能不是想开就开:要看你选的模型本身会不会"看图"(多模态)。\n不确定的话保持关闭最稳妥;勾了但模型不支持,发图片时会报错。'))
        self.ai_in_game = ToggleSwitch(False)
        self.ai_in_game.setToolTip(
            t('玩家在游戏里敲 /ai <描述> 问启动器 AI,不用切出游戏。\n开启后走启动器 AI 的路由(本地/云端/混合),策略跟随启动器选的 ai_strategy\n(云端/混合能真执行指令,如改天气;本地为纯对话)。\n注意:必须【用启动器启动游戏】才会带起游戏内 AI 轮询。'))

        from launcher_app.ui.settings_section import SettingsSection
        common = SettingsSection(t('权限与上下文'))
        cf = QFormLayout()
        common.content.addLayout(cf)
        cf.addRow(t('文件权限:'), self.permission)
        cf.addRow(t('上下文窗口:'), self.context_window)
        cf.addRow(t('图片输入:'), setting_switch_row(t('允许发送图片'), self.vision_check,
                                             t('需要当前模型支持看图')))

        # ---------- 游戏内 AI(独立成组,方便理解/测试) ----------
        ai_group = SettingsSection(t('游戏内 AI'))
        av = ai_group.content
        av.addWidget(setting_switch_row(t('开启游戏内 AI'), self.ai_in_game,
                                        t('在游戏聊天中输入 /ai 调用启动器 AI')))
        ai_explain = QLabel(
            t('开启后,玩家在游戏里敲 /ai(如「/ai 把天气改为雨天」),\n启动器 AI 会按所选策略处理(云端/混合能真执行,结果回显到游戏聊天窗;本地为纯对话)。\n下面的【额度/冷却】保护你的 AI API 额度:多人联机时游戏内玩家都能敲 /ai,\n不设限会被刷、烧光你的 API 额度。'))
        ai_explain.setWordWrap(True)
        ai_explain.setStyleSheet(f"color: {muted_color()};")
        ai_explain.setVisible(False)
        ai_explain_toggle = QToolButton()
        ai_explain_toggle.setText(t('了解游戏内 AI 的额度与权限'))
        ai_explain_toggle.setCheckable(True)
        ai_explain_toggle.setArrowType(Qt.ArrowType.RightArrow)
        ai_explain_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        ai_explain_toggle.setStyleSheet(f"QToolButton {{ color: {muted_color()}; border: none; text-align:left; }}")
        ai_explain_toggle.toggled.connect(lambda opened: (ai_explain.setVisible(opened),
                                                          ai_explain_toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)))
        av.addWidget(ai_explain_toggle)
        av.addWidget(ai_explain)

        # 每日总额度 + 每玩家冷却(保护服主 API)
        self.quota_spin = SettingsSpinBox()
        self.quota_spin.setRange(0, 100000)
        self.quota_spin.setToolTip(t('游戏内 /ai 每日总发言次数上限(0=不限);用超提示玩家明天再试'))
        self.cool_spin = SettingsSpinBox()
        self.cool_spin.setRange(0, 3600)
        self.cool_spin.setSuffix(t(' 秒'))
        self.cool_spin.setToolTip(t('同一玩家两次 /ai 的最小间隔(防单玩家狂刷)'))
        quota_row = QHBoxLayout()
        quota_row.addWidget(self._section_label(t('每日额度(次数):')))
        quota_row.addWidget(self.quota_spin)
        quota_row.addSpacing(16)
        quota_row.addWidget(self._section_label(t('每玩家冷却:')))
        quota_row.addWidget(self.cool_spin)
        quota_row.addStretch()
        av.addLayout(quota_row)

        # 特例豁免名单(=服主/管理员,逗号分隔)
        self.quota_exempt_edit = QLineEdit()
        self.quota_exempt_edit.setPlaceholderText(t('豁免额度的服主/管理员(逗号分隔,如 Steve,Alex;留空=无)'))
        self.quota_exempt_edit.setToolTip(t('这些玩家(=服主/管理员)不受每日额度限制,可任意使用 /ai;仍在每玩家冷却限制内。其他玩家用完额度会提示「去跟服主要」'))
        av.addWidget(self.quota_exempt_edit)

        # ---------- 布局 ----------
        source_row = QHBoxLayout()
        source_row.addWidget(self.strategy_combo, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        strategy_section = SettingsSection(t('模型使用策略'))
        strategy_section.content.addLayout(source_row)
        layout.addWidget(strategy_section)
        layout.addWidget(common)
        layout.addWidget(ai_group)

        # 联动
        self.cloud_provider.currentIndexChanged.connect(self._switch_cloud_provider)
        self.cloud_provider.currentIndexChanged.connect(self._auto_vision)
        self.cloud_model.textChanged.connect(self._auto_vision)
        self.local_mode.currentIndexChanged.connect(self._on_local_mode_changed)
        self.local_mode.currentIndexChanged.connect(self._auto_vision)
        self.local_model.textChanged.connect(self._auto_vision)

        # 云端/本地配置块已由 ModelCardsPanel(模型卡片)接管;这里保留其控件仅供 values() 读取,
        # 必须挂到 self 并隐藏——否则未入布局的 QGroupBox 会变成独立顶层窗口(启动时多弹一个窗口)。
        cloud_box.setParent(self)
        local_box.setParent(self)
        cloud_box.hide()
        local_box.hide()
        self.cloud_box = cloud_box
        self.local_box = local_box

    def _sync_from_settings(self):
        """从 settings 载入(组合/文本设置时屏蔽信号,避免 _fill_* 覆盖用户已存值)。"""
        s = self._settings
        self._loading_provider = True
        self.blockSignals(True)
        # AI 策略:优先读 ai_strategy;旧配置没有时按 ai_source 推导
        strategy = s.get("ai_strategy", "") or ""
        idx = self.strategy_combo.findData(strategy)
        if idx < 0:
            idx = self.strategy_combo.findData(
                "local" if s.get("ai_source", "cloud") == "local" else "cloud_first")
        self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        # 模型类型(API/内置):按 ai_source 推导(local=内置,cloud=API)
        _mt = "builtin" if s.get("ai_source", "cloud") == "local" else "api"
        self.model_type_combo.setCurrentIndex(
            max(0, self.model_type_combo.findData(_mt)))
        # 云端
        self.cloud_provider.setCurrentIndex(
            self.cloud_provider.findData(s.get("ai_cloud_provider", "deepseek")) if self.cloud_provider.findData(
                s.get("ai_cloud_provider", "deepseek")) >= 0 else 0)
        self.cloud_base_url.setText(s.get("ai_cloud_base_url", ""))
        self.cloud_api_key.setText(s.get("ai_cloud_api_key", ""))
        self.cloud_model.setText(s.get("ai_cloud_model", ""))
        self._key_provider = self.cloud_provider.currentData()
        self._provider_keys.setdefault(self._key_provider, s.get('ai_cloud_api_key', ''))
        self.cloud_api_key.setText(self._provider_keys[self._key_provider])
        self._loading_provider = False
        # 本地
        self.local_mode.setCurrentIndex(
            self.local_mode.findData(s.get("ai_local_mode", "builtin")) if self.local_mode.findData(
                s.get("ai_local_mode", "builtin")) >= 0 else 0)
        self.local_endpoint.setText(s.get("ai_local_endpoint", ""))
        self.local_model.setText(s.get("ai_local_model", ""))
        # 通用
        cur = s.get("ai_permission", "launcher_write")
        idx = self.permission.findData(cur)
        self.permission.setCurrentIndex(idx if idx >= 0 else 0)
        # 权限下拉:从只读切到"工作区可写"弹二级确认+免责声明;取消则回只读
        self.permission.currentIndexChanged.connect(self._on_permission_combo_changed)
        self.context_window.setValue(int(s.get("context_window", 65536) or 65536))
        self.vision_check.setChecked(bool(s.get("ai_multimodal", False)))
        ig = str(s.get("ai_in_game", "off") or "off")
        self.ai_in_game.setChecked(ig.strip().lower() not in ("", "off"))
        self.quota_spin.setValue(int(s.get("ai_in_game_quota", 50) or 50))
        self.cool_spin.setValue(int(s.get("ai_in_game_cool", 5) or 5))
        self.quota_exempt_edit.setText(str(s.get("ai_in_game_quota_exempt", "") or ""))
        self.blockSignals(False)
        self._apply_source_visibility()    # 按策略显示云端/本地块
        self._toggle_local_visibility()    # 仅切换子区显隐,不改用户已存值
        self._refresh_local_status()

    # ---- 当前策略 / 来源切换 ----
    def _current_strategy(self) -> str:
        return self.strategy_combo.currentData() or "local_first"

    def _is_cloud(self) -> bool:
        """当前生效来源是否云端(local_first→本地;cloud_first/hybrid→云端生效)。"""
        strategy = self._current_strategy()
        for _key, _label, src, _both in self._STRATEGIES:
            if _key == strategy:
                return src == "cloud"
        return False

    def _apply_source_visibility(self, *_):
        """云端/本地配置块已由模型卡片接管,这里恒隐藏(保留控件仅供 values() 读取),
        绝不 setVisible(True) —— 未入布局的块一旦显示就会变成独立窗口。"""
        self.cloud_box.setVisible(False)
        self.local_box.setVisible(False)

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
            self.local_model.setPlaceholderText(t('输入你已在 LM Studio 加载的模型名'))

    def _fill_cloud_defaults(self):
        idx = self.cloud_provider.currentData()
        if idx == "deepseek":
            self.cloud_base_url.setText("https://api.deepseek.com/v1")
            self.cloud_model.setText("deepseek-chat")
        elif idx == "openrouter":
            self.cloud_base_url.setText("https://openrouter.ai/api/v1")
            self.cloud_model.setText("openrouter/free")
        elif idx == "gemini":
            self.cloud_base_url.setText("https://generativelanguage.googleapis.com/v1beta/openai")
            self.cloud_model.setText("gemini-3.7-flash")
        elif idx == "groq":
            self.cloud_base_url.setText("https://api.groq.com/openai/v1")
            self.cloud_model.setText("openai/gpt-oss-20b")
        elif idx == "cerebras":
            self.cloud_base_url.setText("https://api.cerebras.ai/v1")
            self.cloud_model.setText("gpt-oss-120b")
        elif idx == "siliconflow":
            self.cloud_base_url.setText("https://api.siliconflow.cn/v1")
            self.cloud_model.setText("deepseek-ai/DeepSeek-V4-Flash")
        elif idx == "zhipu":
            self.cloud_base_url.setText("https://open.bigmodel.cn/api/paas/v4")
            self.cloud_model.setText("glm-4.7-flash")
        elif idx == "dashscope":
            self.cloud_base_url.setText("https://dashscope.aliyuncs.com/compatible-mode/v1")
            self.cloud_model.setText("qwen-plus")
        elif idx == "mimo":
            self.cloud_base_url.setText("https://api.xiaomimimo.com/v1")
            self.cloud_model.setText("mimo-v2.6-pro")
        # custom:保留用户输入

    def _switch_cloud_provider(self):
        if getattr(self, '_loading_provider', False):
            return
        if self._key_provider is not None:
            self._provider_keys[self._key_provider] = self.cloud_api_key.text().strip()
        self._key_provider = self.cloud_provider.currentData()
        self.cloud_api_key.setText(self._provider_keys.get(self._key_provider, ''))
        self._fill_cloud_defaults()
        self.remote_models.hide()

    def _choose_remote_model(self, index):
        if self.remote_models.itemData(index):
            self.cloud_model.setText(self.remote_models.itemData(index))

    def _fetch_cloud_models(self):
        from launcher_app.core.background_tasks import BackgroundTask
        from launcher_app.ai.ai_model_list import fetch_models
        if getattr(self, '_models_task', None) and self._models_task.is_running:
            return
        captured = (self.cloud_provider.currentData(), self.cloud_base_url.text().strip(), self.cloud_api_key.text().strip())
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText(t('正在获取…'))
        task = BackgroundTask(lambda current: fetch_models(captured[1], captured[2]), self)
        self._models_task = task
        def still_current():
            return captured == (self.cloud_provider.currentData(), self.cloud_base_url.text().strip(), self.cloud_api_key.text().strip())
        def success(names):
            if not still_current():
                return
            self.remote_models.clear()
            self.remote_models.addItem(t('选择模型（列表不保证全部可调用）'), None)
            for name in names:
                self.remote_models.addItem(name, name)
            _refresh_model_combo_search(self.remote_models)
            self.remote_models.show()
        def failure(error):
            if still_current():
                QMessageBox.information(self, t('获取模型'), str(error))
        def finished():
            self.fetch_models_btn.setEnabled(True)
            self.fetch_models_btn.setText(t('获取模型'))
        task.succeeded.connect(success)
        task.failed.connect(failure)
        task.finished.connect(finished)
        task.start()

    def _refresh_local_status(self):
        """刷新内置本地模型的下载状态文字。"""
        if not hasattr(self, "local_status"):
            return
        try:
            import launcher_app.ai.model_registry as model_registry
            ready = model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            ready = False
        self.local_status.setText(t('内置模型:') + (t('✅ 已下载') if ready else t('未下载(约500MB,点「下载模型」获取)')))

    def _manual_download_local_model(self):
        """手动下载内置本地模型(发行包已含权重,故只手动下载,不自动)。"""
        try:
            import launcher_app.ai.model_registry as model_registry
            if model_registry.is_downloaded(LOCAL_MODEL_ID):
                self.local_status.setText(t('内置模型:✅ 已下载'))
                return
            self.local_status.setText(t('内置模型:下载中…'))
            QApplication.processEvents()
            model_registry.download(LOCAL_MODEL_ID)
            self._refresh_local_status()
        except Exception as e:
            self.local_status.setText(t('内置模型:下载失败({v0})').format(v0=(type(e).__name__)))
            QMessageBox.information(self, t('下载内置模型'), t('下载失败:{v0}\n也可稍后重试。').format(v0=(e)))

    def _auto_vision(self):
        """切服务商/模型时,按所选(生效的)模型是否能看图自动设定「图片输入」开关。"""
        if self._is_cloud():
            prov, model = self.cloud_provider.currentData(), self.cloud_model.text().strip()
        else:
            prov = "local_builtin" if self.local_mode.currentData() == "builtin" else self.local_mode.currentData()
            model = LOCAL_MODEL_ID if prov == "local_builtin" else self.local_model.text().strip()
        vis = model_supports_vision(prov, model)
        if vis is True:
            self.vision_check.setChecked(True)
            self.vision_check.setToolTip(t('该模型看起来支持看图(多模态),已自动开启。'))
        elif vis is False:
            self.vision_check.setChecked(False)
            self.vision_check.setToolTip(t('该模型不支持看图(多模态),图片功能已自动关闭。'))

    def _on_permission_combo_changed(self, idx: int):
        """权限下拉从「只读」切到「工作区可写」→ 弹二级确认+免责声明;取消则回只读。"""
        data = self.permission.itemData(idx)
        if data != "workspace_write":
            return
        from PySide6.QtWidgets import QMessageBox
        plain = self._settings.get("ai_response_style", "plain") == "plain"
        cap = "允许 AI 修改启动器程序？" if plain else "🛡️ 确认给 AI「工作区可写」权限?"
        disc = (("修游戏、装 Mod 和改游戏设置不需要这个权限。\n\n"
                 "开启后，AI 还可以修改启动器功能和插件。只有你打算让 AI 改启动器本身时才建议开启。\n\n"
                 "是否允许？") if plain else
                ("【免责声明】\n一旦开启，AI 就能在启动器程序、设置和游戏目录内创建、修改或删除文件。\n\n"
                 "可能涉及插件、源码和存档；需要稳妥时可切回只读。\n\n确定要开启吗？"))
        ret = QMessageBox.question(self, cap, disc,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                   QMessageBox.StandardButton.Yes)
        if ret != QMessageBox.StandardButton.Yes:
            # 取消 → 回只读
            self.permission.blockSignals(True)
            self.permission.setCurrentIndex(self.permission.findData("readonly"))
            self.permission.blockSignals(False)

    def values(self) -> dict:
        """收集表单内容为设置字段,并据「模型类型」推导「生效」的一组 ai_provider/... 给后端。"""
        self._provider_keys[self.cloud_provider.currentData()] = self.cloud_api_key.text().strip()
        # 模型类型(API/内置)决定生效来源:API→cloud 那组,内置→local builtin
        if self.model_type_combo.currentData() == "builtin":
            source = "local"
            mode = self.local_mode.currentData() or "builtin"
            provider = "local_builtin"
            base_url = ""
            api_key = ""
            model = LOCAL_MODEL_ID
        else:
            source = "cloud"
            provider = self.cloud_provider.currentData()
            base_url = self.cloud_base_url.text().strip()
            api_key = self.cloud_api_key.text().strip()
            model = self.cloud_model.text().strip()
        return {
            "ai_configured": True,
            "ai_source": source,
            "ai_strategy": self._current_strategy(),
            # 云端组
            "ai_cloud_provider": self.cloud_provider.currentData(),
            "ai_cloud_base_url": self.cloud_base_url.text().strip(),
            "ai_cloud_api_key": self.cloud_api_key.text().strip(),
            "ai_cloud_api_keys": dict(self._provider_keys),
            "ai_cloud_model": self.cloud_model.text().strip(),
            # 本地组
            "ai_local_mode": self.local_mode.currentData(),
            "ai_local_endpoint": self.local_endpoint.text().strip(),
            "ai_local_model": (LOCAL_MODEL_ID if self.local_mode.currentData() == "builtin"
                               else self.local_model.text().strip()),
            "ai_local_auto_download": False,
            # 生效(后端读取)
            "ai_provider": provider,
            "ai_base_url": base_url,
            "ai_api_key": api_key,
            "ai_model": model,
            # 通用
            "ai_permission": self.permission.currentData(),
            "ai_response_style": self._settings.get("ai_response_style", "plain"),
            "context_window": self.context_window.value(),
            "ai_multimodal": self.vision_check.isChecked(),
            "ai_in_game": "on" if self.ai_in_game.isChecked() else "off",
            "ai_in_game_quota": int(self.quota_spin.value()),
            "ai_in_game_cool": int(self.cool_spin.value()),
            "ai_in_game_quota_exempt": self.quota_exempt_edit.text().strip(),
        }

class AIQuickSettingsForm(QWidget):
    """Small API-only setup shared by first-run onboarding and the AI dock."""

    valuesChanged = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.provider = QComboBox(self)
        for label, value in _CLOUD_PROVIDERS:
            self.provider.addItem(t(label), value)
        self.base_url = QLineEdit(self)
        self.api_key = QLineEdit(self)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(self)
        self.remote_models = QComboBox(self)
        self.remote_models.addItem(t('点右侧「获取可用模型」后从这里挑…'), None)
        _setup_model_combo(self.remote_models, t('输入关键字搜索模型…'))   # 限高 + 可打字搜索
        self.remote_models.hide()
        self.fetch_models_btn = QPushButton(t('获取可用模型'), self)
        self.fetch_models_btn.setToolTip(t('用当前地址和密钥查询该服务商的模型列表（不发送推理请求），结果可下拉选择'))
        self._keys = dict(self.settings.get("ai_cloud_api_keys") or {})
        self.provider.setCurrentIndex(max(0, self.provider.findData(
            self.settings.get("ai_cloud_provider", "siliconflow"))))
        self.base_url.setText(self.settings.get("ai_cloud_base_url", "https://api.siliconflow.cn/v1"))
        self.model.setText(self.settings.get("ai_cloud_model", "deepseek-ai/DeepSeek-V4-Flash"))
        provider = self.provider.currentData()
        self._active_provider = provider
        self._keys.setdefault(provider, self.settings.get("ai_cloud_api_key", ""))
        self.api_key.setText(self._keys.get(provider, ""))
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.fetch_models_btn.clicked.connect(self._fetch_cloud_models)
        self.remote_models.activated.connect(self._choose_remote_model)
        self.base_url.textChanged.connect(self.remote_models.hide)
        self.api_key.textChanged.connect(self.remote_models.hide)
        # 任一字段改动 → 发 valuesChanged(供自动保存)
        self.provider.currentIndexChanged.connect(self.valuesChanged.emit)
        self.base_url.textChanged.connect(self._emit_values_changed)
        self.api_key.textChanged.connect(self._emit_values_changed)
        self.model.textChanged.connect(self._emit_values_changed)
        form = QFormLayout(self)
        form.addRow(t('服务商'), self.provider)
        form.addRow(t('API 地址'), self.base_url)
        form.addRow(t('API 密钥'), self.api_key)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.fetch_models_btn)
        form.addRow(t('模型'), model_row)
        form.addRow("", self.remote_models)
        # 选型提示:直接告诉用户"多大够用",避免盲目挑大模型
        hint = QLabel(
            t('选型提示：一般<b>模型越大越强、越新越强</b>。但<b>比 DeepSeek-V4-Flash 更大基本没必要</b>——价格涨得快，对启动器场景已属过剩。<br>免费档（Qwen3-8B、R1-Distill-7B 等）只有小模型水平，<b>复杂推理、多步规划、模糊指令都不够用</b>，适合先试水。'))
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        from launcher_app.ui.ui_style import muted_color as _muted_fn
        hint.setStyleSheet(f"color: {_muted_fn()}; font-size: 11px;")
        form.addRow("", hint)
        if self.provider.currentData() == "mimo":
            self.api_key.setToolTip(t('填写 Xiaomi MiMo 按量 API Key（sk-）；Token Plan 额度不适用于本启动器。'))

    def _emit_values_changed(self, *_):
        self.valuesChanged.emit()

    def _provider_changed(self, *_):
        old = getattr(self, "_active_provider", None)
        if old is not None:
            self._keys[old] = self.api_key.text().strip()
        provider = self.provider.currentData()
        self._active_provider = provider
        self.api_key.setText(self._keys.get(provider, ""))
        defaults = {
            "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
            "mimo": ("https://api.xiaomimimo.com/v1", "mimo-v2.6-pro"),
            "openrouter": ("https://openrouter.ai/api/v1", "openrouter/free"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.7-flash"),
            "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-20b"),
            "cerebras": ("https://api.cerebras.ai/v1", "gpt-oss-120b"),
            "siliconflow": ("https://api.siliconflow.cn/v1", "deepseek-ai/DeepSeek-V4-Flash"),
            "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "glm-4.7-flash"),
            "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        }
        if provider in defaults:
            self.base_url.setText(defaults[provider][0])
            self.model.setText(defaults[provider][1])
        self.api_key.setToolTip(
            t('填写 Xiaomi MiMo 按量 API Key（sk-）；Token Plan 额度不适用于本启动器。')
            if provider == "mimo" else "")
        self.remote_models.hide()

    def _choose_remote_model(self, index):
        model = self.remote_models.itemData(index)
        if model:
            self.model.setText(model)

    def _fetch_cloud_models(self):
        from launcher_app.ai.ai_model_list import fetch_models
        from launcher_app.core.background_tasks import BackgroundTask

        if getattr(self, "_models_task", None) and self._models_task.is_running:
            return
        captured = (self.base_url.text().strip(), self.api_key.text().strip())
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText(t('正在获取…'))
        task = BackgroundTask(lambda _current: fetch_models(*captured), self)
        self._models_task = task

        def still_current():
            return captured == (self.base_url.text().strip(), self.api_key.text().strip())

        def success(names):
            if not still_current():
                return
            self.remote_models.clear()
            self.remote_models.addItem(t('选择模型（列表不保证全部可调用）'), None)
            for name in names:
                self.remote_models.addItem(name, name)
            _refresh_model_combo_search(self.remote_models)
            self.remote_models.show()

        def failure(error):
            if still_current():
                QMessageBox.information(self, t('获取模型'), str(error))

        def finished():
            self.fetch_models_btn.setEnabled(True)
            self.fetch_models_btn.setText(t('获取模型'))

        task.succeeded.connect(success)
        task.failed.connect(failure)
        task.finished.connect(finished)
        task.start()

    def values(self):
        provider = self.provider.currentData()
        self._keys[provider] = self.api_key.text().strip()
        return {
            "ai_configured": bool(self.api_key.text().strip()),
            "ai_cloud_provider": provider,
            "ai_cloud_base_url": self.base_url.text().strip(),
            "ai_cloud_api_key": self.api_key.text().strip(),
            "ai_cloud_api_keys": dict(self._keys),
            "ai_cloud_model": self.model.text().strip(),
            "ai_source": "cloud",
            "ai_strategy": "cloud_first",
            "ai_provider": provider,
            "ai_base_url": self.base_url.text().strip(),
            "ai_api_key": self.api_key.text().strip(),
            "ai_model": self.model.text().strip(),
        }

class AISettingsDialog(QDialog):
    """Quick cloud API setup; advanced routing and permissions stay in Settings.
    改动即自动保存,无需手动点「保存」按钮。"""

    def __init__(self, settings: dict, parent=None, autosave=None):
        super().__init__(parent)
        self.setWindowTitle(t('AI 助手设置'))
        self.setMinimumWidth(380)
        self.settings = dict(settings)
        self._autosave = autosave          # (settings_dict) -> None;每次改动后回调持久化
        self.form = AIQuickSettingsForm(settings, self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        hint = QLabel(t('改动会自动保存,无需点保存。'))
        hint.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        layout.addWidget(hint)
        # 表单任一字段变化 → 立即收集并自动保存
        self.form.valuesChanged.connect(self._on_values_changed)

    def _on_values_changed(self):
        self.settings.update(self.form.values())
        if self._autosave is not None:
            self._autosave(self.settings)

    def closeEvent(self, event):
        # 关闭前兜底再存一次,确保最后一处改动不丢
        self._on_values_changed()
        super().closeEvent(event)

    def accept(self):
        self._on_values_changed()
        super().accept()
