# -*- coding: utf-8 -*-
"""
整合包导出:把某个实例的内容按需选文件打包成 .zip(两层:可选是否带启动器)。

**界面**:类似 Windows 选程序安装路径——一个可勾选的目录树,文件夹可展开/收起;
每个文件/文件夹前有复选框。默认勾选「包内容」(mods/config/shaderpacks/资源包/数据包等),
不勾「个人游玩记录」(存档 saves/日志 logs/崩溃报告 crash-reports 等)。

**两层压缩包**:顶层开关「是否带上启动器」——开 = 打包一个外层 zip,里面含启动器 exe +
本整合包;关 = 只打包整合包内容(不含启动器)。
"""
import json
import os
import shutil
import zipfile
import hashlib
import urllib.parse
import urllib.request

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressDialog, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ui_style import card_btn_style, hint_style, set_style

# 顶层目录里「个人游玩记录」类(默认不勾选)
_RECORD_DIRS = {"saves", "logs", "crash-reports", "backups", "schematics",
                "backup", "world", "playerdata"}
# 顶层目录里「启动器/元数据」类(绝不打进包)
_SKIP_DIRS = {"libraries", "versions", "assets", "runtime", "_versions", ".bridge",
              "downloads", "natives", "options.txt"}
# 明确是「包内容」的顶层目录(默认勾选;其余默认不勾)
_CONTENT_DIRS = {"mods", "config", "shaderpacks", "resourcepacks", "datapacks",
                 "defaultconfigs", "kubejs", "tacz", "schematicannon", "scripts",
                 "serverconfig", "patchouli_books", "openloader"}


def _is_record(name: str) -> bool:
    return name in _RECORD_DIRS


def _is_skipped(name: str) -> bool:
    return name in _SKIP_DIRS


def _is_content(name: str) -> bool:
    return name in _CONTENT_DIRS


def _lookup_modrinth(sha1: str) -> dict | None:
    """按 sha1 查 Modrinth 的 version_file,返回 version 对象(含 project_id/files/dependencies)或 None。"""
    if not sha1:
        return None
    try:
        url = "https://api.modrinth.com/v2/version_file/%s?algorithm=sha1" % urllib.parse.quote(sha1)
        req = urllib.request.Request(url, headers={"User-Agent": "AgentLauncher/0.4"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


class PackExportDialog(QDialog):
    """整合包导出的文件选择界面(类似 Windows 选安装路径)。"""

    def __init__(self, inst_id: str, inst_dir: str, parent=None,
                 base: str = "", loader: str = "", loader_version: str = ""):
        super().__init__(parent)
        self.inst_id = inst_id
        self.inst_dir = inst_dir
        self.base = base            # 基础(MC)版本,如 1.20.1(用于 .mrpack 依赖)
        self.loader = loader        # fabric / forge / neoforge
        self.loader_version = loader_version   # 如 0.19.3 / 47.4.23 / 21.1.248
        self.setWindowTitle(f"导出整合包 · {inst_id}")
        self.setMinimumSize(720, 660)
        self._build()
        self._populate()

    # ---- UI ----
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        # ① 顶层开关:是否带启动器(两层压缩包)
        self.include_launcher = QCheckBox("是否带上启动器(两层压缩包):外包 = 启动器 exe + 本整合包;"
                                          "关 = 只打包整合包内容,不含启动器")
        self.include_launcher.setChecked(False)
        self.include_launcher.setToolTip("开:导出的 zip 里含 AgentMinecraftLauncher.exe + 实例内容,朋友解压即装;"
                                         "关:只导整合包内容(适合已装启动器的人)")
        layout.addWidget(self.include_launcher)

        # ①b 导出格式:扁平 .zip / Modrinth .mrpack / CurseForge .zip(拖回启动器/平台可导入)
        fmt_row = QHBoxLayout()
        fmt_label = QLabel("导出格式:")
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItem("Modrinth .mrpack(可直接导入本启动器/Modrinth,推荐)", "mrpack")
        self.fmt_combo.addItem("CurseForge .zip(manifest.json,可导入 CurseForge/多数启动器)", "curseforge")
        self.fmt_combo.addItem("扁平 .zip(纯文件,不含清单)", "zip")
        self.fmt_combo.setToolTip(".mrpack 含 modrinth.index.json + overrides/;"
                                  "CurseForge 含 manifest.json + overrides/(可导入 CurseForge 与常见启动器);"
                                  ".zip 只打包勾选的文件(不带清单)")
        fmt_row.addWidget(fmt_label)
        fmt_row.addWidget(self.fmt_combo, 1)
        layout.addLayout(fmt_row)

        # ② 文件树(可勾选,可展开)
        tree_title = QLabel("勾选要打包的文件(默认勾「包内容」,不勾「个人游玩记录」):")
        layout.addWidget(tree_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setStyleSheet("QTreeWidget { background:#1c2128; color:#e8ecf2;"
                                " border:1px solid #3a4150; border-radius:8px; }")
        layout.addWidget(self.tree, 1)

        # ③ 底部:全选/全不选 + 目标路径 + 导出
        sel_row = QHBoxLayout()
        sel_all = QPushButton("全选包内容"); set_style(sel_all, card_btn_style)
        sel_none = QPushButton("全不选"); set_style(sel_none, card_btn_style)
        sel_all.clicked.connect(lambda: self._check_all(True))
        sel_none.clicked.connect(lambda: self._check_all(False))
        sel_row.addWidget(sel_all); sel_row.addWidget(sel_none); sel_row.addStretch()
        layout.addLayout(sel_row)

        path_label = QLabel("导出到:")
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("选择导出 .zip 的位置")
        browse_btn = QPushButton("浏览…"); set_style(browse_btn, card_btn_style)
        browse_btn.clicked.connect(self._browse_out)
        out_row = QHBoxLayout()
        out_row.addWidget(path_label); out_row.addWidget(self.out_edit, 1); out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        self.export_btn = QPushButton("开始导出")
        set_style(self.export_btn, card_btn_style)
        self.export_btn.setMinimumHeight(34)
        self.export_btn.clicked.connect(self._do_export)
        layout.addWidget(self.export_btn)

        tip = QLabel("提示:存档/日志/崩溃报告默认不勾(个人记录);mods/config/光影/资源包默认勾(包内容)。"
                     "文件夹可点 ▸ 展开逐项选。")
        tip.setWordWrap(True); tip.setStyleSheet(hint_style())
        layout.addWidget(tip)

    def _populate(self):
        self.tree.clear()
        root = self._make_item(self.inst_dir, os.path.basename(self.inst_dir), "",
                               force_content=True)
        root.setExpanded(True)
        self.tree.addTopLevelItem(root)

    def _make_item(self, disk_path: str, label: str, rel: str, force_content=False,
                   inherited=None) -> QTreeWidgetItem:
        """递归构建一棵可勾选的文件树。

        默认勾选规则:包内容(含内容目录下的文件)默认勾;个人记录(存档/日志等)默认不勾;
        启动器/元数据(libraries 等)整项禁用。子项默认继承父项勾选状态(force_content 用于根)。"""
        item = QTreeWidgetItem([label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, Qt.ItemDataRole.UserRole, disk_path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, rel)
        base = os.path.basename(disk_path)
        is_skipped = _is_skipped(base)
        # 计算默认勾选状态:先继承父,再按自身类别覆盖
        if force_content:
            default = Qt.CheckState.Checked
        elif is_skipped:
            default = Qt.CheckState.Unchecked
        elif _is_record(base):
            default = Qt.CheckState.Unchecked
        elif _is_content(base):
            default = Qt.CheckState.Checked
        elif inherited is not None:
            default = inherited
        else:
            default = Qt.CheckState.Unchecked
        item.setCheckState(0, default)
        # 跳过目录/元数据:整项禁用(不进包)
        if is_skipped:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            return item
        # 递归子项(继承父的默认勾选)
        if os.path.isdir(disk_path):
            try:
                for name in sorted(os.listdir(disk_path)):
                    child = self._make_item(os.path.join(disk_path, name), name,
                                            os.path.join(rel, name),
                                            inherited=default)
                    item.addChild(child)
            except OSError:
                pass
        return item

    def _check_all(self, checked: bool):
        def walk(item):
            item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    # ---- 收集选中并压缩 ----
    def _collect_checked(self, item, out_list):
        """递归收集被勾选的 item(只收文件;勾中的文件夹里未勾的子树会漏,需展开收子)。"""
        self._collect_checked_rec(item, out_list, include_self=True)

    def _collect_checked_rec(self, item, out_list, include_self=True):
        if item.checkState(0) != Qt.CheckState.Checked:
            # 未勾的文件夹:仍要递归看其子项(可能出现"子项被勾但父没勾")
            for i in range(item.childCount()):
                self._collect_checked_rec(item.child(i), out_list, include_self=True)
            return
        # 勾中的:若是文件夹,递归把所有勾中的文件收进来
        disk = item.data(0, Qt.ItemDataRole.UserRole)
        if os.path.isfile(disk):
            rel = item.data(0, Qt.ItemDataRole.UserRole + 1)
            out_list.append((disk, rel))
            return
        # 文件夹被勾:默认打包其下所有(除非子项显式取消)
        for i in range(item.childCount()):
            child = item.child(i)
            if child.checkState(0) == Qt.CheckState.Checked:
                self._collect_checked_rec(child, out_list, include_self=True)
            else:
                self._collect_checked_rec(child, out_list, include_self=True)

    def _selected_files(self) -> list:
        files = []
        for i in range(self.tree.topLevelItemCount()):
            self._collect_checked(self.tree.topLevelItem(i), files)
        # 去重(按 rel)
        seen = set(); uniq = []
        for disk, rel in files:
            if rel not in seen:
                seen.add(rel); uniq.append((disk, rel))
        return uniq

    def _browse_out(self):
        ext = ".mrpack" if self.fmt_combo.currentData() == "mrpack" else ".zip"
        flt = "整合包 (*%s)" % ext
        start = self.out_edit.text().strip() or os.path.join(os.path.expanduser("~"), "Desktop")
        d = QFileDialog.getSaveFileName(self, f"保存整合包 (*{ext})", start, flt)
        if d[0]:
            p = d[0]
            if not p.lower().endswith(ext):
                p += ext
            self.out_edit.setText(p)

    def _do_export(self):
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "导出", "请先选择导出位置。")
            return
        files = self._selected_files()
        if not files:
            QMessageBox.warning(self, "导出", "没有勾选任何文件。")
            return
        fmt = self.fmt_combo.currentData()
        # 目标扩展名按格式对齐
        want_ext = ".mrpack" if fmt == "mrpack" else ".zip"
        if not out.lower().endswith(want_ext):
            out += want_ext
            self.out_edit.setText(out)
        progress = QProgressDialog("正在打包...", "", 0, len(files), self)
        progress.setWindowTitle("导出整合包")
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        try:
            if fmt == "mrpack":
                self._write_mrpack(out, files, progress)
            elif fmt == "curseforge":
                self._write_cfzip(out, files, progress)
            else:
                self._write_flat_zip(out, files, progress)
        except Exception as e:
            progress.close()
            QMessageBox.warning(self, "导出失败", f"{type(e).__name__}: {e}")
            return
        progress.close()
        QMessageBox.information(self, "导出完成", f"已导出到:\n{out}\n(共 {len(files)} 个文件)")

    def _write_flat_zip(self, out, files, progress):
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, (disk, rel) in enumerate(files):
                progress.setValue(idx)
                progress.setLabelText(f"打包: {rel}")
                if os.path.isfile(disk):
                    zf.write(disk, "instance/" + rel.replace(os.sep, "/"))
                progress.setValue(idx + 1)
            if self.include_launcher.isChecked():
                exe = self._find_launcher_exe()
                if exe:
                    zf.write(exe, "AgentMinecraftLauncher.exe")

    def _write_cfzip(self, out, files, progress):
        """写 CurseForge .zip:manifest.json + overrides/ 下的勾选文件。

        v1:勾选文件全放 overrides/(导入时覆盖进实例);files[] 留空(不做 CurseForge 哈希回填,
        避免联网/缺失 API key —— 与 mrpack 一致的保守策略,可导入但模组走 overrides)。
        manifestType=minecraftModpack / manifestVersion=1,CurseForge 与多数启动器可识别。"""
        import json as _json
        manifest = {
            "minecraft": {
                "version": self.base,
                "modLoaders": [{"id": f"{self.loader}-{self.loader_version}", "primary": True}] if self.loader and self.loader_version else [],
            },
            "manifestType": "minecraftModpack",
            "manifestVersion": 1,
            "name": self.inst_id,
            "version": "1.0.0",
            "author": "Agent Minecraft Launcher",
            "files": [],
            "overrides": "overrides",
        }
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", _json.dumps(manifest, ensure_ascii=False, indent=2))
            for idx, (disk, rel) in enumerate(files):
                progress.setValue(idx)
                progress.setLabelText(f"打包: {rel}")
                if os.path.isfile(disk):
                    zf.write(disk, "overrides/" + rel.replace(os.sep, "/"))
                progress.setValue(idx + 1)
            if self.include_launcher.isChecked():
                exe = self._find_launcher_exe()
                if exe:
                    zf.write(exe, "AgentMinecraftLauncher.exe")

    def _write_mrpack(self, out, files, progress):
        """写 Modrinth .mrpack:modrinth.index.json + overrides/ 下的勾选文件。

        v1:把所有勾选文件放 overrides/(导入时直接覆盖进实例);files[] 留空
        (不做 Modrinth 哈希回填,避免联网;完全体再补)。dependencies 写 minecraft + 加载器。"""
        import json as _json
        deps = {}
        if self.base:
            deps["minecraft"] = self.base
        lk = {"fabric": "fabric-loader", "forge": "forge", "neoforge": "neoforge"}.get(self.loader or "")
        if lk and self.loader_version:
            deps[lk] = self.loader_version
        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "versionId": self.inst_id,
            "name": self.inst_id,
            "summary": f"由 Agent Minecraft Launcher 从实例 {self.inst_id} 导出",
            "files": [],
            "dependencies": deps,
        }
        # 哈希回填:mods/ 里的 jar 若能在 Modrinth 匹配到版本 → 放进 files[](导入时走 Modrinth 下载+依赖);
        # 匹配不到(本地/非 Modrinth)或非 mods/ 文件 → 放 overrides/。
        modrinth_files = []
        override_files = []
        for disk, rel in files:
            rel_posix = rel.replace(os.sep, "/")
            low = rel_posix.lower()
            if low.startswith("mods/") and low.endswith(".jar"):
                sha1 = self._sha1_of(disk)
                vm = _lookup_modrinth(sha1) if sha1 else None
                if vm:
                    # 收集 mod 依赖(required 项目 → 也放进 files 的 dependencies)
                    deps_of = self._collect_modrinth_deps(vm)
                    primary = next((f for f in (vm.get("files") or []) if f.get("primary")), None) \
                              or (vm.get("files") or [{}])[0]
                    modrinth_files.append({
                        "path": rel_posix,
                        "hashes": primary.get("hashes") or {"sha1": sha1},
                        "env": {"client": "required", "server": "required"},
                        "downloads": primary.get("url") and [primary.get("url")] or [],
                        "fileSize": primary.get("size", 0),
                        "dependencies": deps_of,
                    })
                    continue
            override_files.append((disk, rel_posix))
        index["files"] = modrinth_files
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("modrinth.index.json", _json.dumps(index, ensure_ascii=False, indent=2))
            for idx, (disk, rel_posix) in enumerate(override_files):
                progress.setValue(idx)
                progress.setLabelText(f"打包: {rel_posix}")
                if os.path.isfile(disk):
                    zf.write(disk, "overrides/" + rel_posix)
                progress.setValue(idx + 1)
            if self.include_launcher.isChecked():
                exe = self._find_launcher_exe()
                if exe:
                    zf.write(exe, "AgentMinecraftLauncher.exe")

    @staticmethod
    def _sha1_of(path: str) -> str:
        try:
            h = hashlib.sha1()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def _collect_modrinth_deps(vm: dict) -> list:
        """从 Modrinth version 的 dependencies 里取 required(必装)的项目依赖。"""
        out = []
        for d in (vm.get("dependencies") or []):
            if d.get("dependency_type") == "required":
                proj = d.get("project_id")
                ver = d.get("version_id")
                if proj or ver:
                    out.append({"project_id": proj, "version_id": ver})
        return out

    def _find_launcher_exe(self) -> str | None:
        """找启动器 exe(打包后 = exe 同目录;源码运行回退到 dist/)。"""
        import sys
        if getattr(sys, "frozen", False):
            exe = os.path.join(os.path.dirname(sys.executable), "AgentMinecraftLauncher.exe")
            return exe if os.path.isfile(exe) else None
        import paths
        cand = os.path.join(paths.BASE_DIR, "dist", "AgentMinecraftLauncher.exe")
        return cand if os.path.isfile(cand) else None
