# -*- coding: utf-8 -*-
"""
"下载新实例"的第二级菜单:加载器与组件选择面板。

在"下载新实例"选项卡里:左侧版本树选版本 → 右侧这个面板激活,
在这里选加载器(原版/Fabric/Forge,可扩展)+ 可选光影/优化组件;
默认全部选最新,展开"高级选项"可指定加载器/光影的版本。

加载器列表刻意做成可扩展的:以后加 NeoForge 等,往 LOADER_CHOICES 里加一项即可。
每一项是 (显示名, install_loader 用的名字, Modrinth 加载器名)。
"""
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from agent_tools import OPTIMIZE_MODS, SHADER_MODS  # 可选 Mod 清单(与 CLI/AI 共用)
from loaders import list_fabric_loaders, list_forge_versions
from modrinth import list_mod_versions

# 可扩展的加载器列表:None 表示"原版不装加载器"
LOADER_CHOICES = [
    ("原版(无加载器)", None, None),
    ("Fabric", "fabric", "fabric"),
    ("Forge", "forge", "forge"),
    ("NeoForge", "neoforge", "neoforge"),
]


class LoaderOptionsPanel(QWidget):
    """加载器/组件选择面板。set_mc(版本号) 后自动刷新版本下拉;state() 取全部选择。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mc = ""

        self.hint = QLabel("请先在左侧版本树中选择一个版本")
        self.hint.setStyleSheet("color: gray;")

        # ---- 加载器单选 ----
        self.loader_radios = {}
        loader_box = QVBoxLayout()
        for _name, key, _mr in LOADER_CHOICES:
            radio = QRadioButton(_name)
            if key is None:
                radio.setToolTip("纯原版,不装任何加载器")
            radio.toggled.connect(self._on_loader_toggled)
            self.loader_radios[key] = radio
            loader_box.addWidget(radio)

        # ---- 可选组件 ----
        self.shader_check = QCheckBox("光影加载器(Iris/Oculus,支持光影包)")
        self.optimize_check = QCheckBox("基础优化模组(Sodium 等,显著提升性能)—— 推荐")
        self.optimize_check.setChecked(True)
        self.optimize_check.setToolTip(
            "Fabric: Sodium + Lithium + FerriteCore\nForge: Embeddium + FerriteCore\n原版: 无"
        )

        # ---- 高级选项(可折叠) ----
        self.adv_btn = QPushButton("▼ 高级选项(指定版本)")
        self.adv_btn.setCheckable(True)
        self.adv_btn.toggled.connect(self._toggle_advanced)

        self.adv_container = QWidget()
        self.loader_ver_combo = QComboBox()
        self.loader_ver_combo.setToolTip("加载器版本,默认最新稳定版")
        self.shader_ver_combo = QComboBox()
        self.shader_ver_combo.setToolTip("光影加载器 Mod 的版本,默认最新")
        adv_layout = QVBoxLayout(self.adv_container)
        adv_layout.addWidget(QLabel("加载器版本:"))
        adv_layout.addWidget(self.loader_ver_combo)
        adv_layout.addWidget(QLabel("光影 Mod 版本:"))
        adv_layout.addWidget(self.shader_ver_combo)
        self.adv_container.setVisible(False)

        # ---- 组装 ----
        main_col = QVBoxLayout(self)
        main_col.addWidget(self.hint)
        main_col.addWidget(QLabel("模组加载器:"))
        main_col.addLayout(loader_box)
        main_col.addWidget(self.shader_check)
        main_col.addWidget(self.optimize_check)
        main_col.addWidget(self.adv_btn)
        main_col.addWidget(self.adv_container)
        main_col.addStretch()

        # 默认选 Fabric(最常用,优化/光影都依赖加载器)
        self.loader_radios["fabric"].setChecked(True)

    # ---- 对外接口 ----
    def set_mc(self, mc: str):
        """第 1 步选了版本后调用:显示版本并刷新各版本下拉"""
        self._mc = mc or ""
        self.hint.setText(f"已选版本:{self._mc}  ——  下面选择加载器和组件")
        self._refresh_loader_versions(self._current_loader_key())
        self._refresh_shader_versions(self._current_loader_key())

    def loader_key(self):
        return self._current_loader_key()

    def modrinth_loader(self):
        for _name, key, mr in LOADER_CHOICES:
            if key == self._current_loader_key():
                return mr
        return None

    def state(self) -> dict:
        """收集全部选择,供 create_instance 使用"""
        return {
            "loader_key": self._current_loader_key(),
            "modrinth_loader": self.modrinth_loader(),
            "shader": self.shader_check.isChecked(),
            "optimize": self.optimize_check.isChecked(),
            "loader_version": self.loader_ver_combo.currentData(),
            "shader_version": self.shader_ver_combo.currentData(),
        }

    # ---- 内部 ----
    def _current_loader_key(self):
        for key, radio in self.loader_radios.items():
            if radio.isChecked():
                return key
        return None

    def _on_loader_toggled(self):
        loader = self._current_loader_key()
        has_loader = loader is not None
        self.shader_check.setEnabled(has_loader)
        self.optimize_check.setEnabled(has_loader)
        if not has_loader:
            self.shader_check.setChecked(False)
            self.optimize_check.setChecked(False)
        if self._mc:
            self._refresh_loader_versions(loader)
            self._refresh_shader_versions(loader)

    def _refresh_loader_versions(self, loader):
        self.loader_ver_combo.clear()
        if loader is None or not self._mc:
            self.loader_ver_combo.addItem("(原版无需加载器)", None)
            self.loader_ver_combo.setEnabled(False)
            return
        try:
            versions = (list_fabric_loaders(self._mc) if loader == "fabric"
                        else list_forge_versions(self._mc))
        except Exception:
            versions = []
        self.loader_ver_combo.setEnabled(True)
        if versions:
            for v in versions:
                self.loader_ver_combo.addItem(v, v)
            self.loader_ver_combo.setCurrentIndex(0)  # 默认最新
        else:
            self.loader_ver_combo.addItem("(获取版本失败)", None)

    def _refresh_shader_versions(self, loader):
        self.shader_ver_combo.clear()
        slug = SHADER_MODS.get(loader or "")
        if not slug or not self._mc:
            self.shader_ver_combo.addItem("(未选加载器或无光影)", None)
            self.shader_ver_combo.setEnabled(False)
            return
        try:
            versions = list_mod_versions(slug, self._mc, loader)
        except Exception:
            versions = []
        self.shader_ver_combo.setEnabled(True)
        if versions:
            for v in versions:
                self.shader_ver_combo.addItem(v, v)
            self.shader_ver_combo.setCurrentIndex(0)
        else:
            self.shader_ver_combo.addItem("(该版本暂无光影)", None)

    def _toggle_advanced(self, checked):
        self.adv_btn.setText("▲ 高级选项(指定版本)" if checked else "▼ 高级选项(指定版本)")
        self.adv_container.setVisible(checked)
