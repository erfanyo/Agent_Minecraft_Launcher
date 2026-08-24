# -*- coding: utf-8 -*-
"""
实例管理对话框(类似 PCL 的实例管理,右键实例 → 管理):
- Mod 管理:列出 / 启用 / 禁用 / 删除已装 Mod(.jar ↔ .jar.disabled)
- 数据包管理:按存档列出 datapacks + 从 Modrinth 下载(datapack 分类)
- 光影包管理:shaderpacks 列表 + 从 Modrinth 下载(shader 分类)
- 皮肤管理:检测到 YSM(Yes Steve Model)模组时,管理 ysm 皮肤目录
- 枪包管理:检测到永恒枪械工坊(TACZ)模组时,管理 tacz 枪包目录
- KubeJS 配方:检测到 KubeJS 模组时,管理脚本/配方目录
- 运行配置:一键配置(下拉菜单,未来持续扩展;当前含 RCON 一键配置)
- 备份·存档:手动备份、备份历史(查看/删除)、查看存档、FTB Backups 频率联动
"""
import os
import re
import shutil
import threading

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from backup import backup_instance, list_backups, set_ftb_backup_frequency
from ui_style import hint_style


class _DepGraphWorker(QObject):
    """后台解析 Mod 依赖网络(不卡 UI)。progress(done,total) / done(ModGraph) / error(msg)。"""
    progress = Signal(int, int)
    done = Signal(object)
    error = Signal(str)

    def run(self, mods_dir: str):
        try:
            import mod_deps
            graph = mod_deps.build_graph(mods_dir,
                                         progress_cb=lambda d, t: self.progress.emit(d, t))
            self.done.emit(graph)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


class InstanceManagerDialog(QDialog):
    def __init__(self, instance: dict, game_dir: str, parent=None):
        super().__init__(parent)
        self.inst_id = instance["id"]
        self._inst_base = instance.get("base") or instance["id"]
        self._inst_loader = instance.get("loader")
        self.game_dir = game_dir
        self.inst_dir = os.path.join(game_dir, "versions", instance["id"])
        self.setWindowTitle(f"实例详情: {self.inst_id}")
        self.setMinimumSize(560, 460)
        from ui_style import dialog_dark_style
        self.setStyleSheet(dialog_dark_style())   # 深色兼容:默认控件(菜单/按钮/列表/下拉)统一深色圆角

        self.tabs = QTabWidget()
        from ui_style import tab_style
        self.tabs.setStyleSheet(tab_style())   # 深色兼容:圆角 + 选中高亮,和「我的版本」标签页一致
        self.tabs.addTab(self._build_mods_tab(), "Mod")
        self.tabs.addTab(self._build_pack_tab("datapack"), "数据包")
        self.tabs.addTab(self._build_pack_tab("shader"), "光影包")
        if self._has_mod("ysm", "yes_steve_model", "yesstevemodel", "yes-steve-model"):
            self.tabs.addTab(self._build_ysm_tab(), "皮肤(YSM)")
        if self._has_mod("tacz", "timeless_and_classics", "timeless", "tac_z"):
            self.tabs.addTab(self._build_tacz_tab(), "枪包(TACZ)")
        if self._has_mod("kubejs"):
            self.tabs.addTab(self._build_kubejs_tab(), "KubeJS")
        self.tabs.addTab(self._build_command_tab(), "指令库")
        self.tabs.addTab(self._build_config_tab(), "运行配置")
        self.tabs.addTab(self._build_backup_tab(), "备份·存档")

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    # ---------- 工具 ----------
    def _mod_files(self) -> list:
        mods_dir = os.path.join(self.inst_dir, "mods")
        if not os.path.isdir(mods_dir):
            return []
        return sorted(f for f in os.listdir(mods_dir)
                      if f.lower().endswith(".jar") or f.lower().endswith(".disabled"))

    def _has_mod(self, *keys) -> bool:
        low = " ".join(f.lower() for f in self._mod_files())
        return any(k in low for k in keys)

    def _open_dir(self, path: str):
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _dir_list_widget(self) -> QListWidget:
        w = QListWidget()
        w.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        return w

    # ---------- Mod 管理 ----------
    def _build_mods_tab(self) -> QWidget:
        tab = QWidget()
        self.mods_list = self._dir_list_widget()
        enable_btn = QPushButton("启用所选")
        disable_btn = QPushButton("禁用所选")
        delete_btn = QPushButton("删除所选…")
        open_btn = QPushButton("打开 mods 目录")
        refresh_btn = QPushButton("刷新")
        enable_btn.clicked.connect(lambda: self._toggle_mods(True))
        disable_btn.clicked.connect(lambda: self._toggle_mods(False))
        delete_btn.clicked.connect(self._delete_mods)
        open_btn.clicked.connect(lambda: self._open_dir(os.path.join(self.inst_dir, "mods")))
        refresh_btn.clicked.connect(self._refresh_mods)

        # Mod 依赖网络(灵感 #4/#5):解析该实例各 mod 的依赖关系,画成一张网
        dep_btn = QPushButton("Mod 依赖网络")
        dep_btn.setToolTip("解析本实例 mod 间的依赖/冲突关系,画成一张『谁依赖谁』的网")
        dep_btn.clicked.connect(self._open_dep_graph)

        row = QHBoxLayout()
        for b in (enable_btn, disable_btn, delete_btn, dep_btn, open_btn, refresh_btn):
            row.addWidget(b)
        row.addStretch()

        hint = QLabel("勾选 = 启用;禁用 = 把 .jar 改名为 .jar.disabled(游戏会跳过它,随时可改回)")
        hint.setStyleSheet(hint_style())

        layout = QVBoxLayout(tab)
        layout.addWidget(self.mods_list, 1)
        layout.addLayout(row)
        layout.addWidget(hint)
        self._refresh_mods()
        return tab

    def _refresh_mods(self):
        self.mods_list.clear()
        for f in self._mod_files():
            disabled = f.lower().endswith(".disabled")
            display = f[:-len(".disabled")] if disabled else f
            item = QListWidgetItem(("[已禁用] " if disabled else "") + display)
            item.setData(Qt.ItemDataRole.UserRole, f)
            item.setForeground(Qt.GlobalColor.gray if disabled else Qt.GlobalColor.black)
            self.mods_list.addItem(item)

    def _open_dep_graph(self):
        """「Mod 依赖网络」:后台解析依赖(带进度条)→ 打开网络图。"""
        mods_dir = os.path.join(self.inst_dir, "mods")
        jars = self._mod_files()
        if not jars:
            QMessageBox.information(self, "Mod 依赖网络",
                                    "该实例还没有可分析的 Mod\n(先在 mods 目录放几个 mod,或去下载页装)")
            return
        # 进度条(非模态,带"正在分析依赖关系")
        dlg = QProgressDialog("正在分析依赖关系…", None, 0, len(jars), self)
        dlg.setWindowTitle("Mod 依赖网络")
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setCancelButton(None)
        dlg.setValue(0)
        dlg.show()

        worker = _DepGraphWorker()
        self._dep_worker = worker   # 保持引用,防止 GC 后信号断开
        worker.progress.connect(lambda done, total: (dlg.setMaximum(max(total, 1)), dlg.setValue(done)))

        def on_done(graph):
            dlg.close()
            if graph.stats()["edges"] == 0:
                QMessageBox.information(self, "Mod 依赖网络",
                                        "没解析出 mod 间的依赖关系(可能都只依赖游戏本体/加载器,"
                                        "或元数据不完整)。可点节点看每个 mod 信息。")
                return
            from mod_graph import ModDependencyGraphDialog
            ModDependencyGraphDialog(self.inst_id, graph, self).exec()

        def on_err(msg):
            dlg.close()
            QMessageBox.warning(self, "Mod 依赖网络失败", f"解析依赖出错:\n{msg}")

        worker.done.connect(on_done)
        worker.error.connect(on_err)
        threading.Thread(target=worker.run, args=(mods_dir,), daemon=True).start()

    def _toggle_mods(self, enable: bool):
        mods_dir = os.path.join(self.inst_dir, "mods")
        moved = 0
        for item in self.mods_list.selectedItems():
            actual = item.data(Qt.ItemDataRole.UserRole)
            if actual is None:
                continue
            src = os.path.join(mods_dir, actual)
            if enable and actual.lower().endswith(".disabled"):
                dst = os.path.join(mods_dir, actual[:-len(".disabled")])
            elif not enable and not actual.lower().endswith(".disabled"):
                dst = os.path.join(mods_dir, actual + ".disabled")
            else:
                continue
            try:
                os.rename(src, dst)
                moved += 1
            except OSError:
                pass
        self._refresh_mods()
        if moved:
            self.status_msg(f"已{'启用' if enable else '禁用'} {moved} 个 Mod")

    def _delete_mods(self):
        mods_dir = os.path.join(self.inst_dir, "mods")
        names = [it.data(Qt.ItemDataRole.UserRole) for it in self.mods_list.selectedItems()
                 if it.data(Qt.ItemDataRole.UserRole)]
        if not names:
            return
        if QMessageBox.question(self, "确认删除",
                                f"确定删除 {len(names)} 个 Mod 文件吗?") != QMessageBox.StandardButton.Yes:
            return
        for n in names:
            try:
                os.remove(os.path.join(mods_dir, n))
            except OSError:
                pass
        self._refresh_mods()
        self.status_msg(f"已删除 {len(names)} 个文件")

    # ---------- 数据包 / 光影包(共用结构) ----------
    def _build_pack_tab(self, ptype: str) -> QWidget:
        """ptype: datapack(数据包) 或 shader(光影包)"""
        tab = QWidget()
        title = "数据包" if ptype == "datapack" else "光影包"
        dir_name = "datapacks" if ptype == "datapack" else "shaderpacks"

        # 数据包在存档里,光影包在实例根目录
        if ptype == "datapack":
            self.pack_save_combo = QListWidget()
            self.pack_save_combo.setMaximumHeight(90)
            self.pack_save_combo.itemClicked.connect(lambda _i: self._refresh_pack_list(ptype))
            self.pack_save_combo_label = QLabel("存档(数据包按存档管理):")
        else:
            self.pack_save_combo = None
            self.pack_save_combo_label = QLabel("")

        self.pack_list = self._dir_list_widget()
        dl_btn = QPushButton(f"下载{title}…(Modrinth)")
        dl_btn.clicked.connect(lambda: self._download_pack(ptype))
        open_btn = QPushButton("打开目录")
        open_btn.clicked.connect(lambda: self._open_pack_dir(ptype))
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self._refresh_pack_list(ptype))

        row = QHBoxLayout()
        for b in (dl_btn, open_btn, refresh_btn):
            row.addWidget(b)
        row.addStretch()

        hint = QLabel({
            "datapack": "数据包(如原版数据包 / 小功能包)按存档存放:保存到对应存档的 datapacks 文件夹,进游戏后 /reload 生效",
            "shader": "光影包(如 Complementary / BSL)放进 shaderpacks 文件夹,游戏里 视频设置 → 光影 里启用",
        }[ptype])
        hint.setStyleSheet(hint_style())
        hint.setWordWrap(True)

        layout = QVBoxLayout(tab)
        if self.pack_save_combo:
            layout.addWidget(self.pack_save_combo_label)
            layout.addWidget(self.pack_save_combo)
        layout.addWidget(self.pack_list, 1)
        layout.addLayout(row)
        layout.addWidget(hint)
        self._refresh_pack_list(ptype)
        return tab

    def _pack_base_dir(self, ptype: str) -> str:
        if ptype == "shader":
            return os.path.join(self.inst_dir, "shaderpacks")
        return self.inst_dir  # datapack:下面按存档细分

    def _pack_dest_dir(self, ptype: str) -> str:
        """下载目标目录:光影 = shaderpacks;数据包 = 选中存档的 datapacks"""
        if ptype == "shader":
            return os.path.join(self.inst_dir, "shaderpacks")
        saves_dir = os.path.join(self.inst_dir, "saves")
        if self.pack_save_combo and self.pack_save_combo.currentItem():
            world = self.pack_save_combo.currentItem().text()
        else:
            worlds = sorted(os.listdir(saves_dir)) if os.path.isdir(saves_dir) else []
            world = worlds[0] if worlds else ""
        if not world:
            return os.path.join(self.inst_dir, "saves", "世界未选择")
        return os.path.join(saves_dir, world, "datapacks")

    def _refresh_pack_list(self, ptype: str):
        # 刷新存档下拉(数据包用)
        if self.pack_save_combo:
            current = self.pack_save_combo.currentItem().text() if self.pack_save_combo.currentItem() else ""
            self.pack_save_combo.clear()
            saves_dir = os.path.join(self.inst_dir, "saves")
            worlds = sorted(os.listdir(saves_dir)) if os.path.isdir(saves_dir) else []
            for wd in worlds:
                if os.path.isdir(os.path.join(saves_dir, wd)):
                    self.pack_save_combo.addItem(wd)
            if worlds:
                idx = worlds.index(current) if current in worlds else 0
                self.pack_save_combo.setCurrentRow(idx)
        # 刷新列表
        self.pack_list.clear()
        dest = self._pack_dest_dir(ptype)
        if not os.path.isdir(dest):
            return
        for name in sorted(os.listdir(dest)):
            self.pack_list.addItem(name)

    def _open_pack_dir(self, ptype: str):
        if ptype == "datapack" and not self._pack_dest_dir(ptype).endswith("datapacks"):
            QMessageBox.information(self, "提示", "还没有存档,先创建一个世界后再管理数据包")
            return
        self._open_dir(self._pack_dest_dir(ptype))

    def _download_pack(self, ptype: str):
        title = "数据包" if ptype == "datapack" else "光影包"
        kw, ok = QInputDialog.getText(self, f"下载{title}",
                                      f"输入关键词搜索{title}(Modrinth):")
        if not ok or not kw.strip():
            return
        try:
            from modrinth import download_mod, search_mods
            hits = search_mods(kw.strip(), self._game_version(), None,
                               limit=12, project_type=ptype)
        except Exception as e:
            QMessageBox.warning(self, "搜索失败", str(e))
            return
        if not hits:
            QMessageBox.information(self, "没有结果", f"没找到匹配的{title},换个关键词试试")
            return
        items = [f"{h['title']}  (⬇{h['downloads']:,})" for h in hits]
        choice, ok = QInputDialog.getItem(self, "选择", "选择要下载的项目:", items, 0, False)
        if not ok:
            return
        slug = hits[items.index(choice)]["slug"]
        dest = self._pack_dest_dir(ptype)
        if not os.path.isdir(os.path.dirname(dest)) and ptype == "datapack":
            QMessageBox.information(self, "提示", "还没有存档,先创建一个世界后再下载数据包")
            return
        try:
            filename = download_mod(slug, self._game_version(), None, dest)
        except Exception as e:
            QMessageBox.warning(self, "下载失败", str(e))
            return
        if filename:
            QMessageBox.information(self, "完成", f"已下载到:\n{dest}\n{filename}")
            self._refresh_pack_list(ptype)
        else:
            QMessageBox.warning(self, "没有版本",
                                f"该项目没有 {self._game_version()} 的可用版本")

    def _game_version(self) -> str:
        return self._inst_base

    # ---------- YSM 皮肤 / TACZ 枪包 / KubeJS(共用目录管理) ----------
    def _build_ysm_tab(self) -> QWidget:
        tab = QWidget()
        ysm_dir = os.path.join(self.inst_dir, "ysm")
        self.ysm_list = self._dir_list_widget()
        open_btn = QPushButton("打开皮肤目录")
        open_btn.clicked.connect(lambda: self._open_dir(ysm_dir))
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self._refresh_dir_list(self.ysm_list, ysm_dir))
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(refresh_btn)
        row.addStretch()
        hint = QLabel("检测到 YSM(Yes Steve Model)模组。皮肤文件(.png 贴图 + .model 绑定)放进 ysm 目录,"
                      "进游戏后按 H 打开 YSM 界面即可穿戴管理。")
        hint.setStyleSheet(hint_style())
        hint.setWordWrap(True)
        layout = QVBoxLayout(tab)
        layout.addWidget(self.ysm_list, 1)
        layout.addLayout(row)
        layout.addWidget(hint)
        self._refresh_dir_list(self.ysm_list, ysm_dir)
        return tab

    def _build_tacz_tab(self) -> QWidget:
        tab = QWidget()
        gunpack_dir = os.path.join(self.inst_dir, "tacz", "gunpack")
        self.tacz_list = self._dir_list_widget()
        open_btn = QPushButton("打开枪包目录")
        open_btn.clicked.connect(lambda: self._open_dir(gunpack_dir))
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self._refresh_dir_list(self.tacz_list, gunpack_dir))
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(refresh_btn)
        row.addStretch()
        hint = QLabel("检测到永恒枪械工坊(TACZ)模组。枪包放进 tacz/gunpack 目录(每个子文件夹一个枪包),"
                      "进游戏后用枪械工坊的枪包管理器刷新即可。")
        hint.setStyleSheet(hint_style())
        hint.setWordWrap(True)
        layout = QVBoxLayout(tab)
        layout.addWidget(self.tacz_list, 1)
        layout.addLayout(row)
        layout.addWidget(hint)
        self._refresh_dir_list(self.tacz_list, gunpack_dir)
        return tab

    def _build_kubejs_tab(self) -> QWidget:
        tab = QWidget()
        kjs_dir = os.path.join(self.inst_dir, "kubejs")
        self.kubejs_list = self._dir_list_widget()
        open_btn = QPushButton("打开 KubeJS 目录")
        open_btn.clicked.connect(lambda: self._open_dir(kjs_dir))
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(lambda: self._refresh_kubejs())
        row = QHBoxLayout()
        row.addWidget(open_btn)
        row.addWidget(refresh_btn)
        row.addStretch()
        hint = QLabel("检测到 KubeJS 模组。配方/逻辑脚本在 kubejs/server_scripts/ 下(.js 文件),"
                      "改完进游戏 /reload 生效。列出的文件可选中后删除。")
        hint.setStyleSheet(hint_style())
        hint.setWordWrap(True)
        layout = QVBoxLayout(tab)
        layout.addWidget(self.kubejs_list, 1)
        layout.addLayout(row)
        layout.addWidget(hint)
        self._refresh_kubejs()
        return tab

    def _refresh_kubejs(self):
        self._refresh_dir_list(self.kubejs_list, os.path.join(self.inst_dir, "kubejs", "server_scripts"))

    @staticmethod
    def _refresh_dir_list(list_widget: QListWidget, path: str):
        list_widget.clear()
        if not os.path.isdir(path):
            return
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            suffix = " (目录)" if os.path.isdir(full) else ""
            list_widget.addItem(name + suffix)

    # ---------- 指令库(模板 + 每实例自定义指令) ----------
    def _build_command_tab(self) -> QWidget:
        from command_templates import COMMAND_TEMPLATES
        self.cmd_templates = COMMAND_TEMPLATES
        tab = QWidget()

        # 模板区:分类下拉 + 模板列表
        self.cmd_cat_combo = QComboBox()
        self.cmd_cat_combo.addItems(list(COMMAND_TEMPLATES.keys()))
        self.cmd_template_list = QListWidget()
        self.cmd_template_list.currentItemChanged.connect(self._cmd_template_selected)
        left = QVBoxLayout()
        left.addWidget(QLabel("模板分类:"))
        left.addWidget(self.cmd_cat_combo)
        left.addWidget(QLabel("指令模板:"))
        left.addWidget(self.cmd_template_list, 1)

        # 参数区:动态参数输入 + 预览
        self.cmd_args_box = QWidget()
        self.cmd_args_layout = QVBoxLayout(self.cmd_args_box)
        self.cmd_args_layout.setContentsMargins(0, 0, 0, 0)
        self.cmd_preview = QPlainTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setMaximumHeight(90)
        self.cmd_arg_edits = []
        send_btn = QPushButton("发送到游戏")
        send_btn.clicked.connect(self._cmd_send)
        copy_btn = QPushButton("复制")
        copy_btn.clicked.connect(self._cmd_copy)
        btn_row = QHBoxLayout()
        btn_row.addWidget(send_btn)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        mid = QVBoxLayout()
        mid.addWidget(QLabel("参数(留空用默认):"))
        mid.addWidget(self.cmd_args_box)
        mid.addWidget(QLabel("生成的指令:"))
        mid.addWidget(self.cmd_preview)
        mid.addLayout(btn_row)

        # 自定义指令区:每实例独立保存
        self.cmd_custom_list = QListWidget()
        add_btn = QPushButton("添加自定义指令…")
        add_btn.clicked.connect(self._cmd_add_custom)
        del_btn = QPushButton("删除所选")
        del_btn.clicked.connect(self._cmd_del_custom)
        send2_btn = QPushButton("发送")
        send2_btn.clicked.connect(self._cmd_send_custom)
        copy2_btn = QPushButton("复制")
        copy2_btn.clicked.connect(self._cmd_copy_custom)
        c_row = QHBoxLayout()
        for b in (add_btn, send2_btn, copy2_btn, del_btn):
            c_row.addWidget(b)
        c_row.addStretch()
        right = QVBoxLayout()
        right.addWidget(QLabel("本实例自定义指令(独立保存,可记 mod 专属指令/NBT):"))
        right.addWidget(self.cmd_custom_list, 1)
        right.addLayout(c_row)

        split = QHBoxLayout()
        split.addLayout(left, 2)
        split.addLayout(mid, 2)
        split.addLayout(right, 2)

        hint = QLabel("模板覆盖常用指令;部分 mod 会加额外标签/指令——"
                      "把 mod 专属指令存到右侧「本实例自定义指令」即可,每实例独立。")
        hint.setWordWrap(True)
        hint.setStyleSheet(hint_style())

        layout = QVBoxLayout(tab)
        layout.addLayout(split)
        layout.addWidget(hint)

        self.cmd_cat_combo.currentIndexChanged.connect(self._cmd_reload_templates)
        self._cmd_reload_templates()
        self._cmd_reload_custom()
        return tab

    def _cmd_reload_templates(self):
        self.cmd_template_list.clear()
        cat = self.cmd_cat_combo.currentText()
        for name, _tpl, _args in self.cmd_templates.get(cat, []):
            self.cmd_template_list.addItem(name)
        if self.cmd_template_list.count():
            self.cmd_template_list.setCurrentRow(0)

    def _cmd_current_template(self):
        item = self.cmd_template_list.currentItem()
        if item is None:
            return None
        cat = self.cmd_cat_combo.currentText()
        for name, tpl, args in self.cmd_templates.get(cat, []):
            if name == item.text():
                return (name, tpl, args)
        return None

    def _cmd_template_selected(self, _cur, _prev):
        """选中模板 → 生成参数输入框 + 刷新预览"""
        tpl = self._cmd_current_template()
        # 清空旧参数框
        for w in self.cmd_arg_edits:
            w.deleteLater()
        self.cmd_arg_edits = []
        if tpl is None:
            self.cmd_preview.setPlainText("")
            return
        _name, template, arg_desc = tpl
        arg_names = list(dict.fromkeys(re.findall(r"\{(\w+)\}", template)))
        for i, an in enumerate(arg_names):
            row = QHBoxLayout()
            desc = arg_desc[i] if i < len(arg_desc) else f"{an} 的值"
            lbl = QLabel(an)
            lbl.setFixedWidth(70)
            edit = QLineEdit()
            edit.setPlaceholderText(desc)
            edit.textChanged.connect(self._cmd_update_preview)
            row.addWidget(lbl)
            row.addWidget(edit, 1)
            self.cmd_args_layout.addLayout(row)
            self.cmd_arg_edits.append((an, edit))
        self.cmd_args_layout.addStretch()
        self._cmd_update_preview()

    def _cmd_build_command(self) -> str:
        """按当前参数把模板填好(未填参数保留 {arg} 占位)"""
        tpl = self._cmd_current_template()
        if tpl is None:
            return ""
        _name, template, _args = tpl
        for an, edit in self.cmd_arg_edits:
            val = edit.text().strip()
            if val:
                template = template.replace("{" + an + "}", val)
        return template

    def _cmd_update_preview(self):
        self.cmd_preview.setPlainText(self._cmd_build_command())

    def _cmd_send(self):
        """把生成的指令发送到游戏(多条命令按行拆分逐条发)"""
        cmd = self._cmd_build_command()
        if not cmd.strip():
            return
        main = self.parent()
        from game_command import send_command
        results = []
        for line in cmd.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                results.append(send_command(line, main))
        QMessageBox.information(self, "发送结果", "\n".join(results))

    def _cmd_copy(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._cmd_build_command())
        self.status_msg("指令已复制")

    # ---- 每实例自定义指令 ----
    def _custom_cmd_path(self) -> str:
        return os.path.join(self.inst_dir, ".bridge", "custom_commands.json")

    def _cmd_load_custom(self) -> list:
        p = self._custom_cmd_path()
        if not os.path.isfile(p):
            return []
        try:
            import json
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("commands", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def _cmd_save_custom(self, commands: list):
        import json
        os.makedirs(os.path.dirname(self._custom_cmd_path()), exist_ok=True)
        with open(self._custom_cmd_path(), "w", encoding="utf-8") as f:
            json.dump({"instance": self.inst_id, "commands": commands},
                      f, ensure_ascii=False, indent=2)

    def _cmd_reload_custom(self):
        self.cmd_custom_list.clear()
        for c in self._cmd_load_custom():
            self.cmd_custom_list.addItem(f"{c.get('name', '?')}  →  {c.get('command', '')[:40]}")

    def _cmd_add_custom(self):
        name, ok1 = QInputDialog.getText(self, "添加自定义指令", "名称(如:模组专属召唤):")
        if not ok1 or not name.strip():
            return
        cmd, ok2 = QInputDialog.getText(self, "添加自定义指令", "指令内容(可含 NBT):")
        if not ok2 or not cmd.strip():
            return
        commands = self._cmd_load_custom()
        commands.append({"name": name.strip(), "command": cmd.strip()})
        self._cmd_save_custom(commands)
        self._cmd_reload_custom()

    def _cmd_del_custom(self):
        it = self.cmd_custom_list.currentItem()
        if it is None:
            return
        if QMessageBox.question(self, "确认", "删除这条自定义指令?") != QMessageBox.StandardButton.Yes:
            return
        commands = self._cmd_load_custom()
        idx = self.cmd_custom_list.currentRow()
        if 0 <= idx < len(commands):
            commands.pop(idx)
            self._cmd_save_custom(commands)
            self._cmd_reload_custom()

    def _cmd_send_custom(self):
        it = self.cmd_custom_list.currentItem()
        if it is None:
            return
        commands = self._cmd_load_custom()
        idx = self.cmd_custom_list.currentRow()
        if not (0 <= idx < len(commands)):
            return
        main = self.parent()
        from game_command import send_command
        results = []
        for line in commands[idx]["command"].splitlines():
            line = line.strip()
            if line:
                results.append(send_command(line, main))
        QMessageBox.information(self, "发送结果", "\n".join(results))

    def _cmd_copy_custom(self):
        it = self.cmd_custom_list.currentItem()
        if it is None:
            return
        commands = self._cmd_load_custom()
        idx = self.cmd_custom_list.currentRow()
        if 0 <= idx < len(commands):
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(commands[idx]["command"])
            self.status_msg("指令已复制")

    # ---------- 运行配置:一键配置(下拉菜单,未来持续扩展) ----------
    def _build_config_tab(self) -> QWidget:
        tab = QWidget()
        hint = QLabel("「一键配置」集中管理各类运行配置:点下拉按钮选择要配置的项目。\n"
                      "以后会逐渐添加更多配置项,都从这里进入。")
        hint.setWordWrap(True)
        hint.setStyleSheet(hint_style())

        btn = QToolButton()
        btn.setText("一键配置 ▾")
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        # 正式方案:bridge-mod(本地指令口)
        menu.addAction("一键配置 bridge-mod(本地指令口,推荐)", self._one_click_bridge)
        # 临时方案:RCON(需对局域网开放)
        rcon_item = menu.addAction("一键配置 RCON(临时方案)", self._one_click_rcon)
        rcon_item.setToolTip("临时方案:需要 Lan Server Properties,进世界后按 ESC → 对局域网开放")
        btn.setMenu(menu)

        refresh_btn = QPushButton("刷新状态")
        refresh_btn.clicked.connect(self._refresh_config_status)

        self.config_status = QLabel("")
        self.config_status.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(btn)
        row.addWidget(refresh_btn)
        row.addStretch()

        layout = QVBoxLayout(tab)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(self.config_status)
        layout.addStretch()
        self._refresh_config_status()
        return tab

    def _refresh_config_status(self):
        """显示 RCON 当前状态:已就绪 / 待配置 / 未装 mod"""
        from game_command import has_lan_server_properties, read_rcon_config
        rc = read_rcon_config(self.inst_dir)
        if rc:
            self.config_status.setText(
                f"✅ RCON 已就绪:端口 {rc['port']},密码 {rc['password']}\n"
                "(游戏重新进入世界后即可直接发指令)")
            return
        if has_lan_server_properties(self.inst_dir):
            self.config_status.setText(
                "🔧 已检测到 Lan Server Properties,但 RCON 还没配置。\n"
                "点「一键配置 ▾ → 一键配置 RCON」自动写好 server.properties。")
        else:
            self.config_status.setText(
                "⚠️ 未检测到 Lan Server Properties mod。\n"
                "先在「下载 Mod」页搜 lanserverproperties 装到该实例,"
                "再回来一键配置。")

    def _one_click_bridge(self):
        """一键配置 bridge-mod(本地指令口,推荐):委托主窗口执行"""
        parent = self.parent()
        if parent is not None and hasattr(parent, "_one_click_bridge_for"):
            parent._one_click_bridge_for({"id": self.inst_id,
                                          "base": self._inst_base,
                                          "loader": self._inst_loader})
        else:
            self.config_status.setText("请在主窗口「我的版本」里对实例执行一键配置")

    def _one_click_rcon(self):
        """一键配置 RCON(临时方案,需对局域网开放)"""
        from game_command import ensure_rcon_config
        msg = ensure_rcon_config(self.inst_dir)
        self.config_status.setText(msg)
        if "已自动配置" in msg or "已配置好" in msg:
            self.status_msg("RCON 一键配置完成(临时方案:进世界按 ESC → 对局域网开放)")

    # ---------- 备份 · 存档 ----------
    def _build_backup_tab(self) -> QWidget:
        tab = QWidget()
        self.bak_list = self._dir_list_widget()
        backup_btn = QPushButton("立即备份")
        backup_btn.clicked.connect(self._do_backup)
        open_bak_btn = QPushButton("打开备份目录")
        open_bak_btn.clicked.connect(lambda: self._open_dir(os.path.join(self.game_dir, "backups", self.inst_id)))
        del_bak_btn = QPushButton("删除所选备份…")
        del_bak_btn.clicked.connect(self._delete_backup)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_backups)
        row1 = QHBoxLayout()
        for b in (backup_btn, open_bak_btn, del_bak_btn, refresh_btn):
            row1.addWidget(b)
        row1.addStretch()

        # FTB Backups 联动
        ftb_label = QLabel("FTB Backups 自动备份间隔(分钟):")
        self.ftb_spin = QSpinBox()
        self.ftb_spin.setRange(1, 1440)
        self.ftb_spin.setValue(30)
        ftb_btn = QPushButton("应用到 FTB Backups 配置")
        ftb_btn.clicked.connect(self._apply_ftb)
        self.ftb_status = QLabel("")
        self.ftb_status.setStyleSheet(hint_style())
        self.ftb_status.setWordWrap(True)
        ftb_row = QHBoxLayout()
        ftb_row.addWidget(ftb_label)
        ftb_row.addWidget(self.ftb_spin)
        ftb_row.addWidget(ftb_btn)
        ftb_row.addStretch()

        # 存档查看
        self.saves_list = self._dir_list_widget()
        self.saves_list.setMaximumHeight(110)
        open_save_btn = QPushButton("打开所选存档目录")
        open_save_btn.clicked.connect(self._open_selected_save)
        del_save_btn = QPushButton("删除所选存档…")
        del_save_btn.clicked.connect(self._delete_selected_save)
        saves_row = QHBoxLayout()
        saves_row.addWidget(QLabel("存档(saves):"))
        saves_row.addWidget(open_save_btn)
        saves_row.addWidget(del_save_btn)
        saves_row.addStretch()

        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("备份历史:"))
        layout.addWidget(self.bak_list, 1)
        layout.addLayout(row1)
        layout.addLayout(ftb_row)
        layout.addWidget(self.ftb_status)
        layout.addLayout(saves_row)
        layout.addWidget(self.saves_list)
        self._refresh_backups()
        self._refresh_saves()
        return tab

    def _do_backup(self):
        try:
            out = backup_instance(self.inst_id, self.game_dir)
            self.status_msg(f"备份完成:{out}")
        except Exception as e:
            QMessageBox.warning(self, "备份失败", str(e))
        self._refresh_backups()

    def _refresh_backups(self):
        self.bak_list.clear()
        for b in list_backups(self.inst_id, self.game_dir):
            tag = ("[存档]" if b["has_saves"] else "") + ("[Mod列表]" if b["has_mods"] else "")
            self.bak_list.addItem(f"{b['stamp']}  {tag}")

    def _delete_backup(self):
        items = self.bak_list.selectedItems()
        if not items:
            return
        if QMessageBox.question(self, "确认删除", f"删除 {len(items)} 个备份?") != QMessageBox.StandardButton.Yes:
            return
        for it in items:
            shutil.rmtree(os.path.join(self.game_dir, "backups", self.inst_id, it.text().split()[0]),
                          ignore_errors=True)
        self._refresh_backups()

    def _apply_ftb(self):
        msg = set_ftb_backup_frequency(self.inst_id, self.ftb_spin.value(), self.game_dir)
        self.ftb_status.setText(msg)
        if "已修改" in msg:
            self.status_msg(msg)

    def _refresh_saves(self):
        self.saves_list.clear()
        saves_dir = os.path.join(self.inst_dir, "saves")
        if not os.path.isdir(saves_dir):
            return
        for name in sorted(os.listdir(saves_dir)):
            if os.path.isdir(os.path.join(saves_dir, name)):
                self.saves_list.addItem(name)

    def _open_selected_save(self):
        it = self.saves_list.currentItem()
        if it is None:
            QMessageBox.information(self, "提示", "先在列表里选一个存档")
            return
        self._open_dir(os.path.join(self.inst_dir, "saves", it.text()))

    def _delete_selected_save(self):
        it = self.saves_list.currentItem()
        if it is None:
            QMessageBox.information(self, "提示", "先在列表里选一个存档")
            return
        if QMessageBox.question(self, "确认删除",
                                f"确定删除存档 {it.text()} 吗?\n(建议先备份)") != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(os.path.join(self.inst_dir, "saves", it.text()), ignore_errors=True)
        self._refresh_saves()

    # ---------- 杂项 ----------
    def status_msg(self, text: str):
        if self.parent():
            sb = getattr(self.parent(), "statusBar", None)
            if sb:
                sb().showMessage(text)
