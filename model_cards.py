# -*- coding: utf-8 -*-
"""模型卡片面板(DSH 风格)——前端组件,纯 Qt,不碰后端路由。

参考 DeepSeek Harness 的模型管理卡片:
  · 顶部一排卡片,每张 = 一个模型服务商/内置模型;
  · 卡片头:名称 + 状态圆点 + 「编辑」「删除」;
  · 点卡片展开:API 密钥 / (折叠)自定义设置 → API 地址 / 模型目录(多行 id+显示名+删);
  · 底部「+ 添加模型」;内置模型卡片展开内容不同(下载状态 + 下载按钮 + 推理后端)。

数据契约(与 assistant/settings 现有字段对齐,不改后端路由):
  ai_cloud_provider / ai_cloud_base_url / ai_cloud_api_key / ai_cloud_model  仍为「当前生效」;
  ai_cloud_models: {provider_id: [{"id":..., "name":...}, ...]}  每个服务商的模型目录;
  ai_cloud_api_keys: {provider_id: key}  已存的各服务商密钥;
  内置:ai_local_model(固定内置 id)。
仅前端渲染与编辑,变化通过 values() 导出为设置字段。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui_style import (accent_color, current_color, muted_color, set_style,
                      text_color, danger_color, success_color)


def _provider_label(pid: str) -> str:
    try:
        from assistant import _CLOUD_PROVIDERS
        for label, value in _CLOUD_PROVIDERS:
            if value == pid:
                return label
    except Exception:
        pass
    return pid


def _default_models(pid: str) -> list:
    """各服务商的默认模型目录(id, 显示名);没有就空。"""
    presets = {
        # 硅基流动:模型多,预置几档供摸索。显示名里直接写明定位,省得用户逐个试。
        # 规律:越大越强(但超过 DeepSeek-V4-Flash 基本没必要)、越新越强。
        "siliconflow": [
            ("deepseek-ai/DeepSeek-V4-Flash", "DeepSeek-V4-Flash(推荐:便宜、1M 上下文)"),
            ("nex-agi/Nex-N2-Pro", "Nex-N2-Pro(免费:397B MoE,工具调用强)"),
            ("Qwen/Qwen3-8B", "Qwen3-8B(免费但小:复杂/多步任务不够用)"),
            ("Qwen/Qwen3.6-35B-A3B", "Qwen3.6-35B-A3B(中等:35B MoE 仅激活 3B,快)"),
            ("Qwen/Qwen3.5-27B", "Qwen3.5-27B(小模型档)"),
            ("deepseek-ai/DeepSeek-R1-Distill-Qwen-7B", "R1-Distill-Qwen-7B(免费:推理蒸馏)"),
        ],
        "deepseek": [("deepseek-chat", "DeepSeek-V3"), ("deepseek-reasoner", "DeepSeek-R1")],
        "mimo": [("mimo-v2.6-flash", "MiMo-V2.6-Flash"),
                 ("mimo-v2.6-pro", "MiMo-V2.6-Pro"),
                 ("mimo-v2.6-pro-ultraspeed", "MiMo-V2.6-Pro-UltraSpeed")],
        "zhipu": [("glm-4.7-flash", "GLM-4.7-Flash"), ("glm-4.7", "GLM-4.7")],
        "openrouter": [("openrouter/auto", "Auto Router")],
        "gemini": [("gemini-3.7-flash", "Gemini-3.7-Flash")],
        "dashscope": [("qwen-plus", "Qwen-Plus")],
    }
    return [{"id": i, "name": n} for i, n in presets.get(pid, [])]


def fetch_names(base_url: str, api_key: str) -> list:
    """后台线程里查询 /models(模块级函数,便于 BackgroundTask 调用)。"""
    from ai_model_list import fetch_models
    return fetch_models(base_url, api_key)


class ModelRow(QWidget):
    """模型目录里的一行:模型 id + 显示名 + 展开箭头 + 删除。"""
    changed = Signal()
    removed = Signal()

    def __init__(self, model_id="", display="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(6)
        self.id_edit = QLineEdit(model_id)
        self.id_edit.setPlaceholderText("模型 id")
        self.name_edit = QLineEdit(display)
        self.name_edit.setPlaceholderText("显示名")
        self.del_btn = QPushButton("🗑")
        self.del_btn.setFixedSize(26, 26)
        self.del_btn.setToolTip("删除这个模型")
        lay.addWidget(self.id_edit, 1)
        lay.addWidget(self.name_edit, 1)
        lay.addWidget(self.del_btn)
        self.id_edit.textChanged.connect(self.changed.emit)
        self.name_edit.textChanged.connect(self.changed.emit)
        self.del_btn.clicked.connect(self.removed.emit)
        for w in (self.id_edit, self.name_edit):
            set_style(w, lambda: (
                f"QLineEdit {{ background: {current_color('bg0')}; color: {text_color()};"
                f" border: 1px solid {current_color('btn_border')}; border-radius: 7px;"
                " padding: 4px 8px; }"))
        set_style(self.del_btn, lambda: (
            "QPushButton { background: transparent; border: none; font-size: 13px; }"
            f"QPushButton:hover {{ color: {danger_color()}; }}"))

    def data(self) -> dict:
        return {"id": self.id_edit.text().strip(), "name": self.name_edit.text().strip()}


class ProviderCard(QFrame):
    """一张模型卡片:头部(名称+状态点+编辑/删除) + 可展开内容。"""
    edited = Signal()
    removed = Signal()
    changed = Signal()

    def __init__(self, kind: str, pid: str, data: dict, parent=None):
        super().__init__(parent)
        self.kind = kind          # "api" / "builtin"
        self.pid = pid
        self._data = dict(data)
        self._expanded = False
        self.setObjectName("ModelCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._build()
        self._apply_style()
        self.set_expanded(False)

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # 头部
        head = QHBoxLayout()
        head.setSpacing(10)
        self.title = QLabel(self._title_text())
        self.title.setStyleSheet(f"font-size:15px; font-weight:bold; color:{text_color()};")
        self.dot = QLabel("●")
        self._update_dot()
        self.edit_btn = QPushButton("编辑")
        self.del_btn = QPushButton("删除")
        for b, col in ((self.edit_btn, muted_color()), (self.del_btn, danger_color())):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: transparent; color: {col};"
                            " border: 1px solid transparent; border-radius: 6px;"
                            " padding: 3px 10px; font-size: 12px; }"
                            f"QPushButton:hover {{ border-color: {col}; }}")
        head.addWidget(self.title)
        head.addWidget(self.dot)
        head.addStretch()
        head.addWidget(self.edit_btn)
        head.addWidget(self.del_btn)
        root.addLayout(head)

        # 展开内容
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        if self.kind == "builtin":
            self._build_builtin(body)
        else:
            self._build_api(body)

        root.addWidget(self.body)
        self.edit_btn.clicked.connect(self._toggle_expanded)
        self.del_btn.clicked.connect(self.removed.emit)

    def _build_api(self, body):
        self.api_key = QLineEdit(self._data.get("api_key", ""))
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("API 密钥")
        body.addWidget(QLabel("API 密钥"))
        body.addWidget(self.api_key)

        # 自定义设置(折叠)
        self.adv_toggle = QPushButton("自定义设置  ▾")
        self.adv_toggle.setStyleSheet(f"QPushButton {{ background: transparent; color: {muted_color()};"
                                      " border: none; text-align: left; font-size: 12px; }")
        body.addWidget(self.adv_toggle)
        self.adv_body = QWidget()
        adv = QVBoxLayout(self.adv_body)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(8)
        self.base_url = QLineEdit(self._data.get("base_url", ""))
        self.base_url.setPlaceholderText("API 地址")
        adv.addWidget(QLabel("API 地址"))
        adv.addWidget(self.base_url)
        body.addWidget(self.adv_body)
        self._adv_open = False
        self.adv_body.setVisible(False)
        self.adv_toggle.clicked.connect(self._toggle_adv)

        # 模型目录(限长滚动 + 超过 20 项顶部配搜索框)
        mlabel = QHBoxLayout()
        mlabel.addWidget(QLabel("模型目录"))
        self.models_count = QLabel("")
        self.models_count.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        mlabel.addWidget(self.models_count)
        mlabel.addStretch()
        self.reset_btn = QPushButton("恢复默认模型")
        self.fetch_btn = QPushButton("获取可用模型")
        for b in (self.reset_btn, self.fetch_btn):
            b.setStyleSheet(f"QPushButton {{ background: transparent; color: {accent_color()};"
                            " border: none; font-size: 12px; }"
                            f"QPushButton:hover {{ text-decoration: underline; }}")
        mlabel.addWidget(self.reset_btn)
        mlabel.addWidget(self.fetch_btn)
        body.addLayout(mlabel)

        # 搜索框(仅当条目多时才显示)
        self.models_search = QLineEdit()
        self.models_search.setPlaceholderText("搜索模型…")
        self.models_search.setClearButtonEnabled(True)
        self.models_search.textChanged.connect(self._apply_model_filter)
        self.models_search.setVisible(False)
        body.addWidget(self.models_search)

        self.models_box = QVBoxLayout()
        self.models_box.setSpacing(4)
        self.models_box.setContentsMargins(0, 0, 0, 0)
        self.models_host = QWidget()
        self.models_host.setLayout(self.models_box)
        self.models_scroll = QScrollArea()
        self.models_scroll.setWidgetResizable(True)
        self.models_scroll.setWidget(self.models_host)
        self.models_scroll.setMaximumHeight(200)   # 列表再长也不撑爆卡片
        self.models_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.models_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        body.addWidget(self.models_scroll)
        self.add_model_btn = QPushButton("+ 添加模型")
        self.add_model_btn.setStyleSheet(f"QPushButton {{ color: {muted_color()};"
                                         f" border: 1px dashed {current_color('btn_border')};"
                                         " border-radius: 7px; padding: 6px; }"
                                         f"QPushButton:hover {{ border-color: {accent_color()}; }}")
        body.addWidget(self.add_model_btn)

        self._rows = []
        for m in self._data.get("models", []) or _default_models(self.pid):
            self._add_row(m.get("id", ""), m.get("name", ""), emit=False)
        self.add_model_btn.clicked.connect(lambda: self._add_row("", ""))
        self.reset_btn.clicked.connect(self._reset_models)
        self.fetch_btn.clicked.connect(self._fetch_models)
        self._after_rows_changed()

    def _build_builtin(self, body):
        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {muted_color()};")
        body.addWidget(self.status)
        self.backend = QComboBox()
        self.backend.addItem("自动(优先 Vulkan)", "auto")
        self.backend.addItem("仅 CPU", "cpu")
        self.backend.addItem("Vulkan GPU", "vulkan")
        cur = self._data.get("gpu", "auto")
        i = self.backend.findData(cur)
        self.backend.setCurrentIndex(i if i >= 0 else 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("推理后端:"))
        row.addWidget(self.backend, 1)
        body.addLayout(row)
        self.dl_btn = QPushButton("下载模型")
        self.dl_btn.clicked.connect(self._download)
        body.addWidget(self.dl_btn)
        self.explainer = QLabel("内置离线小模型:适合基础问答与直白指令;模糊/复杂任务建议用 API 模型。")
        self.explainer.setWordWrap(True)
        self.explainer.setStyleSheet(f"color: {muted_color()}; font-size: 11px;")
        body.addWidget(self.explainer)
        self._refresh_builtin_status()
        self.backend.currentIndexChanged.connect(self.changed.emit)

    # ---------- 交互 ----------
    def _toggle_expanded(self):
        self.set_expanded(not self._expanded)

    def set_expanded(self, on: bool):
        self._expanded = bool(on)
        self.body.setVisible(self._expanded)
        self.edit_btn.setText("收起" if self._expanded else "编辑")

    def _toggle_adv(self):
        self._adv_open = not self._adv_open
        self.adv_body.setVisible(self._adv_open)
        self.adv_toggle.setText(("自定义设置  ▴" if self._adv_open else "自定义设置  ▾"))

    # ---------- 模型目录:增删 / 过滤 / 获取 ----------
    def _after_rows_changed(self):
        """行数变化后:更新计数、按需显示搜索框、重新套用过滤。"""
        n = len(self._rows)
        if hasattr(self, "models_count"):
            self.models_count.setText(f"共 {n} 个" if n else "")
        if hasattr(self, "models_search"):
            need = n > 20                      # 超过 20 项才配搜索框
            self.models_search.setVisible(need)
            if not need and self.models_search.text():
                self.models_search.blockSignals(True)
                self.models_search.clear()
                self.models_search.blockSignals(False)
        self._apply_model_filter()

    def _apply_model_filter(self):
        """按搜索词过滤模型行(匹配模型 id 或显示名)。"""
        if not hasattr(self, "models_search"):
            return
        q = self.models_search.text().strip().lower()
        for row in self._rows:
            if not q:
                row.setVisible(True)
            else:
                hay = (row.id_edit.text() + " " + row.name_edit.text()).lower()
                row.setVisible(q in hay)

    def _add_row(self, mid="", name="", emit=True):
        row = ModelRow(mid, name)
        row.changed.connect(self.changed.emit)
        row.changed.connect(self._apply_model_filter)   # 编辑后重新过滤
        row.removed.connect(lambda: self._remove_row(row))
        self.models_box.addWidget(row)
        self._rows.append(row)
        self._after_rows_changed()
        if emit:
            self.changed.emit()

    def _remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._after_rows_changed()
        self.changed.emit()

    def _reset_models(self):
        while self._rows:
            self._remove_row(self._rows[0])
        for m in _default_models(self.pid):
            self._add_row(m["id"], m["name"], emit=False)
        self._after_rows_changed()
        self.changed.emit()

    def _fetch_models(self):
        """后台查询 /models 填入目录。

        修复:以前是同步调用且 `except Exception: pass` 静默吞掉,表现为「点了没反应 / 卡界面」。
        现在放后台线程,失败弹提示,并且目录长度封顶(配合滚动 + 搜索)。
        """
        base = self.base_url.text().strip()
        key = self.api_key.text().strip()
        if not base:
            QMessageBox.information(self, "获取可用模型",
                                    "请先在「自定义设置」里填写 API 地址。")
            return
        if getattr(self, "_fetch_task", None) is not None and self._fetch_task.is_running:
            return
        from background_tasks import BackgroundTask
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("正在获取…")
        task = BackgroundTask(lambda _current: fetch_names(base, key), self)
        self._fetch_task = task

        def on_ok(names):
            while self._rows:
                self._remove_row(self._rows[0])
            for n in (names or [])[:300]:
                self._add_row(n, n, emit=False)
            self._after_rows_changed()
            self.changed.emit()

        def on_err(error):
            QMessageBox.information(self, "获取可用模型", str(error))

        def on_done():
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("获取可用模型")

        task.succeeded.connect(on_ok)
        task.failed.connect(on_err)
        task.finished.connect(on_done)
        task.start()

    def _download(self):
        try:
            import model_registry
            from assistant import LOCAL_MODEL_ID
            self.status.setText("内置模型:下载中…")
            model_registry.download(LOCAL_MODEL_ID)
        except Exception as e:
            self.status.setText(f"内置模型:下载失败({type(e).__name__})")
        self._refresh_builtin_status()

    def _refresh_builtin_status(self):
        try:
            import model_registry
            from assistant import LOCAL_MODEL_ID
            ready = model_registry.is_downloaded(LOCAL_MODEL_ID)
        except Exception:
            ready = False
        self.status.setText("内置模型:" + ("✅ 已下载" if ready else "未下载(约500MB,可点下载获取)"))

    def _update_dot(self):
        ok = bool(self._data.get("api_key") or self.kind == "builtin")
        self.dot.setStyleSheet(f"color: {success_color() if ok else muted_color()}; font-size: 11px;")

    def _title_text(self):
        return "内置模型" if self.kind == "builtin" else _provider_label(self.pid)

    def _apply_style(self):
        set_style(self, lambda: (
            f"QFrame#ModelCard {{ background: {current_color('panel_bg')};"
            f" border: 1px solid {current_color('panel_border')}; border-radius: 12px; }}"))

    # ---------- 数据 ----------
    def collect(self) -> dict:
        if self.kind == "builtin":
            return {"gpu": self.backend.currentData()}
        return {
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip(),
            "models": [r.data() for r in self._rows if r.data()["id"]],
        }


class ModelCardsPanel(QWidget):
    """模型卡片列表 + 底部「+ 添加模型」。values() 导出为设置字段。"""
    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._settings = dict(settings)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_box = QWidget()
        self.cards_lay = QVBoxLayout(self.cards_box)
        self.cards_lay.setContentsMargins(0, 0, 6, 0)
        self.cards_lay.setSpacing(10)
        self.cards_lay.addStretch()
        scroll.setWidget(self.cards_box)
        outer.addWidget(scroll, 1)
        self.add_btn = QPushButton("+ 添加模型")
        self.add_btn.setStyleSheet(f"QPushButton {{ color: {muted_color()};"
                                   f" border: 1px dashed {current_color('btn_border')};"
                                   " border-radius: 8px; padding: 8px; }"
                                   f"QPushButton:hover {{ border-color: {accent_color()}; }}")
        self.add_btn.clicked.connect(self._add_provider_card)
        outer.addWidget(self.add_btn)

        self._cards = []
        self._load()

    def _load(self):
        s = self._settings
        models_map = dict(s.get("ai_cloud_models") or {})
        keys = dict(s.get("ai_cloud_api_keys") or {})
        # 内置卡片(固定一张)
        builtin = ProviderCard("builtin", "builtin", {
            "gpu": s.get("ai_local_gpu", "auto"),
        })
        self._insert_card(builtin)
        # 当前生效的云端服务商卡
        pid = s.get("ai_cloud_provider", "deepseek")
        data = {
            "api_key": keys.get(pid, s.get("ai_cloud_api_key", "")),
            "base_url": s.get("ai_cloud_base_url", ""),
            "models": models_map.get(pid) or _default_models(pid),
        }
        card = ProviderCard("api", pid, data)
        card.set_expanded(True)
        self._insert_card(card)

    def _insert_card(self, card):
        card.changed.connect(self.changed.emit)
        card.removed.connect(lambda: self._remove_card(card))
        self.cards_lay.insertWidget(self.cards_lay.count() - 1, card)
        self._cards.append(card)

    def _remove_card(self, card):
        if card.kind == "builtin":
            return   # 内置卡不可删
        if card in self._cards:
            self._cards.remove(card)
        card.setParent(None)
        card.deleteLater()
        self.changed.emit()

    def _add_provider_card(self):
        """弹服务商选择菜单,让用户挑要添加哪个供应商(不再按预设顺序硬塞)。"""
        from assistant import _CLOUD_PROVIDERS
        from PySide6.QtWidgets import QMenu
        from ui_style import popup_menu_style
        menu = QMenu(self)
        menu.setStyleSheet(popup_menu_style())
        for label, value in _CLOUD_PROVIDERS:
            act = menu.addAction(label)
            act.setData(value)
        chosen = menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))
        if not chosen:
            return
        pid = chosen.data() or "custom"
        card = ProviderCard("api", pid, {"models": _default_models(pid)})
        card.set_expanded(True)
        self._insert_card(card)
        self.changed.emit()

    def values(self) -> dict:
        """导出为设置字段(保持后端契约)。当前生效 = 第一张 api 卡。"""
        out = {"ai_source": "cloud"}
        api_cards = [c for c in self._cards if c.kind == "api"]
        models_map = {}
        keys = {}
        for c in api_cards:
            d = c.collect()
            models_map[c.pid] = d["models"]
            keys[c.pid] = d["api_key"]
        out["ai_cloud_models"] = models_map
        out["ai_cloud_api_keys"] = keys
        active = api_cards[0] if api_cards else None
        if active:
            d = active.collect()
            out["ai_cloud_provider"] = active.pid
            out["ai_cloud_base_url"] = d["base_url"]
            out["ai_cloud_api_key"] = d["api_key"]
            out["ai_cloud_model"] = (d["models"][0]["id"] if d["models"] else "")
        for c in self._cards:
            if c.kind == "builtin":
                out["ai_local_gpu"] = c.collect().get("gpu", "auto")
        return out
