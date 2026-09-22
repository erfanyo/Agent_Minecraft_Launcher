# -*- coding: utf-8 -*-
"""服务端详情页:与客户端实例详情同构(同一个 CenterShell 骨架、同一套章节风格)。

为什么单独成文件而不是塞进 ``instance_manager``:那边是 1300+ 行且承载客户端
全部逻辑,把服务端并进去既难读也容易碰坏已跑通的路径。``CenterShell`` 本来就是
为「多页面共用一套左菜单+右面板」设计的,这里新建一个用同一骨架即为「同一套配置」。

**「高级选项」折叠分组**:KubeJS、server.properties 这类不是每天都碰的东西收进
可折叠分组;展开状态按**服务端各自**记忆(写进该服务端的 ``.amcl-server.json``),
这样「工作服」和「和朋友玩的那个服」互不干扰。
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPushButton, QVBoxLayout, QWidget)

from center_shell import CenterShell
from server_packs import (list_servers, read_candidate_report,
                          read_server_ui_state, write_server_ui_state)
from ui_style import hint_style

#: 高级选项分组的持久化键
ADVANCED_KEY = 'advanced_open'


def server_sections():
    """章节定义(名称, 分组 id 或 None)。分组 id 为 None 表示顶层章节。

    抽成纯数据便于单测断言「服务端与客户端章节对齐」这件事本身。
    """
    return [
        ('概览', None),
        ('Mod', None),
        ('玩家名单', None),
        ('运行配置', None),
        ('备份·存档', None),
        ('高级选项', '__group__'),
        ('server.properties', 'advanced'),
        ('KubeJS', 'advanced'),
        ('诊断', 'advanced'),
    ]


class ServerDetailsView(QWidget):
    """可嵌入主窗口的服务端详情视图(非模态,支持 set_server 复用)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = None
        self.server_dir = ''
        self.shell = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel('未选择服务端。')
        self.placeholder.setStyleSheet(hint_style())
        self._layout.addWidget(self.placeholder)

    # ---------- 生命周期 ----------
    def set_server(self, server: dict, force: bool = False):
        """填充某个服务端记录;同一个服务端重复调用直接跳过(避免无谓重建)。"""
        if server is None:
            self._clear()
            return
        server_id = server.get('id')
        if (not force and self.shell is not None
                and getattr(self, 'server_id', None) == server_id):
            return
        self.server = server
        self.server_id = server_id
        self.server_dir = server.get('path') or ''
        self._rebuild()

    def _drop_shell(self):
        """销毁当前 shell 控件。

        先 ``setParent(None)`` 再 ``deleteLater()``:只调 deleteLater 时,子控件
        (LeftMenu、各章节面板)的析构顺序由事件循环与父对象共同决定,实测在反复
        重建/清空时会出现悬空子对象并触发原生访问违例(0xC0000005)。解除父子
        关系后再排队删除,顺序才是确定的。
        """
        if self.shell is None:
            return
        self._layout.removeWidget(self.shell)
        self.shell.setParent(None)
        self.shell.deleteLater()
        self.shell = None

    def _clear(self):
        self._drop_shell()
        self.server = None
        self.server_id = None
        self.placeholder.setVisible(True)

    def _rebuild(self):
        self._drop_shell()
        self.placeholder.setVisible(False)
        self.shell = CenterShell(self, menu_width=150)
        opened = bool(read_server_ui_state(self.server, ADVANCED_KEY, False))
        for label, group in server_sections():
            if group == '__group__':
                self.shell.add_section_group('advanced', label, open_state=opened)
            elif group:
                self.shell.add_grouped_section(
                    group, label, self._builder_for(label))
            else:
                self.shell.add_section(label, self._builder_for(label))
        self.shell.menu.groupToggled.connect(self._persist_advanced)
        self._layout.addWidget(self.shell)
        self.shell.switch_to(0)

    def _persist_advanced(self, group_id: str, opened: bool):
        if group_id == 'advanced' and self.server is not None:
            write_server_ui_state(self.server, ADVANCED_KEY, bool(opened))

    def _builder_for(self, label: str):
        return {
            '概览': self._build_overview,
            'Mod': self._build_mods,
            '玩家名单': self._build_players,
            '运行配置': self._build_runtime,
            '备份·存档': self._build_backups,
            'server.properties': self._build_properties,
            'KubeJS': self._build_kubejs,
            '诊断': self._build_diagnosis,
        }.get(label, self._build_placeholder)

    # ---------- 各章节 ----------
    def _panel(self, title: str, hint: str = '') -> tuple:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        if hint:
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet(hint_style())
            layout.addWidget(note)
        return tab, layout

    def _build_overview(self) -> QWidget:
        report = (self.server or {}).get('report') or {}
        tab, layout = self._panel('概览')
        rows = [
            ('名称', (self.server or {}).get('name') or '未命名'),
            ('类型', '候选服务端' if (self.server or {}).get('candidate') else '普通服务端'),
            ('Minecraft', report.get('minecraftVersion') or '未确认'),
            ('加载器', f"{report.get('loader', 'unknown')} {report.get('loaderVersion') or ''}".strip()),
            ('目录', self.server_dir or '未确认'),
            ('验证状态', (report.get('verification') or {}).get('label') or '未验证'),
        ]
        for name, value in rows:
            layout.addWidget(QLabel(f'<b>{name}</b>：{value}'))
        warnings = report.get('warnings') or []
        if warnings:
            layout.addWidget(QLabel('<b>转换时的提醒</b>'))
            for item in warnings:
                layout.addWidget(QLabel('· ' + str(item)))
        layout.addStretch()
        return tab

    def _build_mods(self) -> QWidget:
        tab, layout = self._panel(
            'Mod', '列出服务端 mods 目录。停用/启用请用「诊断」页或让 AI 助手处理(会先取证)。')
        listing = QListWidget()
        mods_dir = os.path.join(self.server_dir, 'mods')
        if os.path.isdir(mods_dir):
            for name in sorted(os.listdir(mods_dir)):
                if name.lower().endswith(('.jar', '.jar.disabled')):
                    state = '已停用' if name.lower().endswith('.disabled') else '启用'
                    listing.addItem(f'[{state}] {name}')
        else:
            listing.addItem('(没有 mods 目录)')
        layout.addWidget(listing, 1)
        return tab

    def _build_players(self) -> QWidget:
        """白名单 / OP / 封禁:在同一个页面里分类管理。"""
        import server_players as spl
        tab, layout = self._panel(
            '玩家名单',
            '管理白名单、OP 与封禁。文件格式错误时启动器会拒绝写入，'
            '以免把整份名单覆盖掉；服务端运行时也拒绝修改。')
        self._player_lists = {}
        for kind in ('whitelist', 'ops', 'banned-players', 'banned-ips'):
            box = QGroupBox(spl.label_for(kind) + f'（{spl.filename_for(kind)}）')
            column = QVBoxLayout(box)
            status = QLabel('')
            status.setWordWrap(True)
            listing = QListWidget()

            add_row = QHBoxLayout()
            name_edit = QLineEdit()
            name_edit.setPlaceholderText('玩家名（封禁 IP 时填 IP）')
            add_btn = QPushButton('添加')
            remove_btn = QPushButton('移除选中')
            add_row.addWidget(name_edit, 1)
            add_row.addWidget(add_btn)
            add_row.addWidget(remove_btn)

            def refresh(kind=kind, listing=listing, status=status):
                entries, error = spl.read_entries(self.server_dir, kind)
                listing.clear()
                if error:
                    status.setText('⛔ ' + error)
                    return
                for entry in entries:
                    extra = ''
                    if kind == 'ops':
                        extra = f"  Lv{entry.get('level', '?')}"
                    elif entry.get('reason'):
                        extra = f"  （{entry['reason']}）"
                    listing.addItem(spl.entry_name(entry) + extra)
                status.setText(f'共 {len(entries)} 条。')

            def do_add(kind=kind, edit=name_edit, refresh=refresh, status=status):
                name = edit.text().strip()
                if not name:
                    return
                entries, error = spl.read_entries(self.server_dir, kind)
                if error:
                    status.setText('⛔ ' + error)
                    return
                try:
                    updated = spl.add_entry(entries, kind, name=name)
                except ValueError as exc:
                    status.setText(f'⛔ {exc}')
                    return
                result = spl.apply_entries(self.server_dir, kind, updated)
                status.setText(('✅ ' if result['ok'] else '⛔ ') + result['message'])
                if result['ok']:
                    edit.clear()
                    refresh()

            def do_remove(kind=kind, listing=listing, refresh=refresh, status=status):
                item = listing.currentItem()
                if item is None:
                    return
                # 列表里带了后缀(Lv/原因),只取显示名部分
                name = item.text().split('  ')[0].strip()
                entries, error = spl.read_entries(self.server_dir, kind)
                if error:
                    status.setText('⛔ ' + error)
                    return
                result = spl.apply_entries(
                    self.server_dir, kind, spl.remove_entry(entries, name))
                status.setText(('✅ ' if result['ok'] else '⛔ ') + result['message'])
                if result['ok']:
                    refresh()

            add_btn.clicked.connect(do_add)
            remove_btn.clicked.connect(do_remove)
            column.addWidget(listing)
            column.addLayout(add_row)
            column.addWidget(status)
            refresh()
            self._player_lists[kind] = refresh
            layout.addWidget(box)
        return tab

    def _build_runtime(self) -> QWidget:
        tab, layout = self._panel(
            '运行配置', '内存、Java、启动参数等运行期设置。')
        report = (self.server or {}).get('report') or {}
        rows = [
            ('加载器', f"{report.get('loader', 'unknown')} "
                       f"{report.get('loaderVersion') or ''}".strip()),
            ('Minecraft', report.get('minecraftVersion') or '未确认'),
            ('需要 Java', str(report.get('requiredJava') or '未记录')),
            ('启动入口', (report.get('verification') or {}).get('entry') or '未静态验证'),
            ('EULA', '已接受' if report.get('eulaAccepted') else '未接受（首次启动需确认）'),
        ]
        for name, value in rows:
            label = QLabel(f'<b>{name}</b>：{value}')
            label.setWordWrap(True)
            layout.addWidget(label)
        note = QLabel('这些值来自转换时生成的报告。内存与 JVM 参数的逐项修改'
                      '会接到客户端同一套「启动设置」体系上（尚未接线）。')
        note.setWordWrap(True)
        note.setStyleSheet(hint_style())
        layout.addWidget(note)
        layout.addStretch()
        return tab

    def _build_backups(self) -> QWidget:
        tab, layout = self._panel(
            '备份·存档', '服务端的存档与备份。')
        rows = [
            ('世界目录', os.path.join(self.server_dir, 'world')),
            ('mods', os.path.join(self.server_dir, 'mods')),
            ('crash-reports', os.path.join(self.server_dir, 'crash-reports')),
        ]
        for name, path in rows:
            exists = os.path.isdir(path)
            count = ''
            if exists:
                try:
                    count = f'（{len(os.listdir(path))} 项）'
                except OSError:
                    count = ''
            state = '存在' if exists else '不存在'
            label = QLabel(f'<b>{name}</b>：{state}{count}')
            label.setWordWrap(True)
            layout.addWidget(label)
        world_size = self._dir_size(os.path.join(self.server_dir, 'world'))
        size_label = QLabel(f'<b>世界占用</b>：{world_size}')
        layout.addWidget(size_label)
        layout.addStretch()
        return tab

    @staticmethod
    def _dir_size(path: str) -> str:
        """世界目录大小(人类可读);失败返回「未知」。"""
        if not os.path.isdir(path):
            return '未知'
        total = 0
        for base, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(base, name))
                except OSError:
                    continue
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if total < 1024 or unit == 'TB':
                return f'{total:.1f} {unit}' if unit != 'B' else f'{total} B'
            total /= 1024.0
        return '未知'

    def _build_properties(self) -> QWidget:
        from server_properties_io import properties_path, server_running
        from server_properties_ui import edit_server_properties
        tab, layout = self._panel(
            'server.properties',
            '可视化编辑服务端总配置。保存前会自动备份为 server.properties.bak；'
            '服务端运行时不允许修改。')
        path = properties_path(self.server_dir)
        state = QLabel('')
        state.setWordWrap(True)
        info = QLabel(f'文件：{path}')
        info.setWordWrap(True)
        info.setStyleSheet(hint_style())

        def refresh():
            if not os.path.isfile(path):
                state.setText('⚠ 还没有 server.properties（服务端首次启动后会自动生成）。')
            elif server_running(self.server_dir):
                state.setText('⛔ 服务端正在运行：现在不能改配置，请先停止服务端。')
            else:
                state.setText('✅ 可以编辑。')

        edit_btn = QPushButton('打开可视化编辑…')

        def do_edit():
            result = edit_server_properties(self.server_dir, self)
            state.setText(('✅ ' if result['ok'] else '⛔ ') + result['message'])
            refresh()

        edit_btn.clicked.connect(do_edit)
        open_btn = QPushButton('打开所在目录')

        def do_open():
            from os_platform.openpath import open_path
            open_path(self.server_dir)

        open_btn.clicked.connect(do_open)
        row = QHBoxLayout()
        row.addWidget(edit_btn)
        row.addWidget(open_btn)
        row.addStretch()
        layout.addWidget(info)
        layout.addLayout(row)
        layout.addWidget(state)
        layout.addStretch()
        refresh()
        return tab

    def _build_kubejs(self) -> QWidget:
        from kubejs_viewer import KubejsViewer
        tab, layout = self._panel(
            'KubeJS', '展开查看脚本内容（只读）。脚本报错常导致服务端直接起不来。')
        viewer = KubejsViewer(os.path.join(self.server_dir, 'kubejs'))
        layout.addWidget(viewer, 1)
        return tab

    def _build_diagnosis(self) -> QWidget:
        from server_log_diagnosis import (build_diagnosis, suggestions_to_markdown)
        tab, layout = self._panel(
            '诊断', '结合崩溃报告与本次日志，给出「建议停用哪些 Mod」及各自说明。'
                    '这里只给建议，不会自动改动任何文件。')
        text = self._diagnose_text()
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(body.textInteractionFlags()
                                     | body.textInteractionFlags().TextSelectableByMouse)
        layout.addWidget(body)
        layout.addStretch()
        return tab

    def _diagnose_text(self) -> str:
        """跑一遍只读诊断并返回 Markdown 表格文本。"""
        from mod_deps import read_mod_metadata
        from server_log_diagnosis import build_diagnosis, suggestions_to_markdown
        mods_dir = os.path.join(self.server_dir, 'mods')
        mods = []
        if os.path.isdir(mods_dir):
            for name in sorted(os.listdir(mods_dir)):
                lowered = name.lower()
                if not lowered.endswith(('.jar', '.jar.disabled')):
                    continue
                path = os.path.join(mods_dir, name)
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                info = read_mod_metadata(path) or {}
                mods.append({'file': name, 'modId': str(info.get('id') or ''),
                             'name': str(info.get('name') or name),
                             'environment': info.get('environment', 'unknown'),
                             'description': '', 'disabled': lowered.endswith('.disabled'),
                             'path': path})
        log_text = self._collect_log()
        result = build_diagnosis(mods, log_text)
        return suggestions_to_markdown(result)

    def _collect_log(self) -> str:
        """收集本次日志与最近的崩溃报告(只读)。"""
        chunks = []
        candidates = [
            os.path.join(self.server_dir, 'logs', 'latest.log'),
            os.path.join(self.server_dir, 'logs', 'kubejs', 'server.log'),
        ]
        crashes = os.path.join(self.server_dir, 'crash-reports')
        if os.path.isdir(crashes):
            reports = sorted(f for f in os.listdir(crashes) if f.endswith('.txt'))
            if reports:
                candidates.append(os.path.join(crashes, reports[-1]))
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding='utf-8', errors='replace') as stream:
                    chunks.append(stream.read(512 * 1024))
            except OSError:
                continue
        return '\n'.join(chunks)

    def _build_placeholder(self) -> QWidget:
        tab, layout = self._panel('（未实现）')
        layout.addStretch()
        return tab


#: 与 ``InstanceDetailsView`` 对应的别名,便于主窗口沿用同一命名习惯。
ServerDetails = ServerDetailsView
