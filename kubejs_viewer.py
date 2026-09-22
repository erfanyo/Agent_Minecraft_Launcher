# -*- coding: utf-8 -*-
"""KubeJS 脚本查看器（只读）。

**现状**：本模块已退化为「插件用的界面组件」——入口在插件
``plugins/kubejs_tools.py``（主标签页「KubeJS 工具」），核心的服务端详情不再自带
KubeJS 页。保留在核心是因为**插件之间不能互相 import**（插件目录下每个 ``.py``
都会被插件系统当成一个插件加载），所以插件要用的组件只能放核心。

**为什么是插件**：KubeJS 只有整合包作者会看，普通玩家不关心 `server_scripts` 里
有什么；按项目约定（core 只留大众功能）以插件承载。

能力刻意保持「能看就行」：只读浏览（不编辑——编辑在外部编辑器里做更好，不跟
VS Code 比），外加「从日志跳到报错那一行」。

纯逻辑（目录树 / 文本判定 / 读文件）在核心 :mod:`kubejs_scripts`；报错定位的解析
在 :mod:`kubejs_errors`。本模块只负责界面与装配。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import (QColor, QFont, QTextCharFormat, QTextCursor,
                           QTextFormat)
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton,
                               QSplitter, QTextEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from kubejs_scripts import (MAX_PREVIEW_CHARS, build_script_tree, is_viewable,
                            read_script)
from ui_style import (current_color, hint_style, list_style, muted_color,
                      set_style)

class KubejsViewer(QWidget):
    """左树右内容。``root`` 传 ``kubejs`` 目录(客户端或服务端通用)。"""

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self.root = root
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.title = QLabel('')
        self.title.setStyleSheet(f'color:{muted_color()};')
        self.errors_btn = QPushButton('报错定位')
        self.errors_btn.setToolTip('从服务端日志里找出 KubeJS 报错，点一下跳到出错的那一行')
        self.errors_btn.setCheckable(True)
        self.errors_btn.toggled.connect(self._toggle_errors)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh)
        open_btn = QPushButton('打开目录')
        open_btn.clicked.connect(self._open_dir)
        row.addWidget(self.title, 1)
        row.addWidget(self.errors_btn)
        row.addWidget(refresh_btn)
        row.addWidget(open_btn)
        layout.addLayout(row)

        # 报错面板(默认收起):不占地方,按一下才出现
        self.errors_panel = QGroupBox('KubeJS 报错定位')
        errors_layout = QVBoxLayout(self.errors_panel)
        self.errors_summary = QLabel('')
        self.errors_summary.setWordWrap(True)
        self.errors_summary.setStyleSheet(f'color:{muted_color()};')
        self.errors_list = QListWidget()
        set_style(self.errors_list, list_style)
        self.errors_list.currentItemChanged.connect(self._on_error_selected)
        self.errors_hint = QLabel('')
        self.errors_hint.setWordWrap(True)
        self.errors_hint.setStyleSheet(hint_style())
        errors_layout.addWidget(self.errors_summary)
        errors_layout.addWidget(self.errors_list)
        errors_layout.addWidget(self.errors_hint)
        self.errors_panel.hide()
        layout.addWidget(self.errors_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['脚本', ''])
        self.tree.setColumnWidth(0, 220)
        set_style(self.tree, list_style)
        self.tree.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self.tree)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont('Consolas')
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.view.setFont(font)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 540])
        layout.addWidget(splitter, 1)

        note = QLabel('只读查看。脚本语法错误会让服务端直接启动失败——'
                      '这时改脚本是唯一的排查手段。')
        note.setWordWrap(True)
        note.setStyleSheet(hint_style())
        layout.addWidget(note)

    # ---------- 数据 ----------
    def refresh(self):
        self.tree.clear()
        self.view.setPlainText('')
        if not os.path.isdir(self.root):
            self.title.setText('未找到 kubejs 目录')
            return
        tree = build_script_tree(self.root)
        count = self._count_files(tree)
        self.title.setText(f'{os.path.basename(self.root)} · 共 {count} 个文件')
        for node in tree:
            self.tree.addTopLevelItem(self._make_item(node))
        self.tree.expandToDepth(0)

    @staticmethod
    def _count_files(nodes: list) -> int:
        total = 0
        for node in nodes:
            total += 1 if not node['is_dir'] else KubejsViewer._count_files(node['children'])
        return total

    def _make_item(self, node: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node['name'], ''])
        item.setData(0, Qt.ItemDataRole.UserRole, node['path'])
        if node['is_dir']:
            for child in node['children']:
                item.addChild(self._make_item(child))
        elif not is_viewable(node['path']):
            item.setForeground(0, self.palette().text())
            item.setText(1, '(不可预览)')
        return item

    # ---------- 交互 ----------
    def _on_select(self, current, _previous):
        if current is None:
            return
        path = current.data(0, Qt.ItemDataRole.UserRole)
        if not path or os.path.isdir(path):
            self.view.setPlainText('')
            return
        if not is_viewable(path):
            self.view.setPlainText('（这种文件不支持预览，可点「打开目录」用系统编辑器查看）')
            return
        text, truncated, error = read_script(path)
        if error:
            self.view.setPlainText(error)
            return
        header = f'// {os.path.relpath(path, self.root)}\n' if truncated else ''
        tail = (f'\n\n… 文件过大，此处只显示前 {MAX_PREVIEW_CHARS} 个字符。'
                if truncated else '')
        self.view.setPlainText(header + text + tail)

    # ---------- 报错定位 ----------
    def _toggle_errors(self, checked: bool):
        self.errors_panel.setVisible(bool(checked))
        if checked:
            self.reload_errors()

    def reload_errors(self):
        """重新采集日志并列出 KubeJS 报错(由外部把日志文本塞进来时用 set_log)。"""
        import kubejs_errors as ke
        errors = ke.parse_errors(getattr(self, '_log_text', ''))
        self._errors = errors
        self.errors_list.clear()
        self.errors_summary.setText(ke.summarize(errors))
        self.errors_hint.setText('')
        if not errors:
            return
        for group in ke.group_by_file(errors):
            for record in group['errors']:
                item = QListWidgetItem(
                    f"{record['relpath']}#{record['line']}  "
                    f"{record['kind'] or '报错'}")
                item.setToolTip(f"{record['time']}  {record['title']}\n"
                                f"{record['message']}")
                # 元素存整条记录,选中时据此跳转
                item.setData(Qt.ItemDataRole.UserRole, record)
                self.errors_list.addItem(item)

    def set_log(self, text: str):
        """交给查看器的日志文本(来自服务端 logs / crash-reports)。"""
        self._log_text = str(text or '')
        if self.errors_btn.isChecked():
            self.reload_errors()

    def _on_error_selected(self, current, _previous):
        if current is None:
            return
        record = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(record, dict):
            return
        import kubejs_errors as ke
        path = ke.resolve_path(self.root, record.get('relpath', ''))
        if not path:
            self.view.setPlainText(
                f"找不到脚本文件：{record.get('relpath')}#{record.get('line')}\n"
                '（可能已被删除或改名；也可能它不在 kubejs 的脚本目录下）')
            self.errors_hint.setText('')
            return
        info = ke.read_excerpt(path, record.get('line', 1))
        if info['error']:
            self.view.setPlainText(info['error'])
            return
        self._show_excerpt(info, record)
        hints = ke.hints_for(record)
        self.errors_hint.setText('\n'.join('· ' + h for h in hints))

    def _show_excerpt(self, info: dict, record: dict):
        """显示片段并把出错行高亮出来。"""
        header = (f"// {record.get('relpath')}#{record.get('line')}\n"
                  f"// {record.get('kind') or '报错'}: {record.get('message')}\n"
                  f"// ---- 出错行在第 {record.get('line')} 行 ----\n")
        self.view.setPlainText(header + info['text'])
        if info['error_index'] < 0:
            return
        # 正文行数 = 头部行数 + 片段内偏移;把该行整行加底色并滚动到它
        header_lines = header.count('\n')
        block = self.view.document().findBlockByNumber(
            header_lines + info['error_index'])
        if not block.isValid():
            return
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(block)
        selection.format = QTextCharFormat()
        # 用主题的选中底色,跟随深浅模式;不用硬编码色值
        selection.format.setBackground(QColor(current_color('sel_bg')))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.view.setExtraSelections([selection])
        cursor = QTextCursor(block)
        self.view.setTextCursor(cursor)
        self.view.centerCursor()

    def select_file(self, relpath: str, line: int = 1) -> bool:
        """选中某个脚本(相对 kubejs 根)并高亮指定行;找到返回 True。"""
        import kubejs_errors as ke
        target = ke.resolve_path(self.root, relpath)
        if not target:
            return False
        item = self._find_item(target)
        if item is None:
            return False
        self.tree.setCurrentItem(item)
        info = ke.read_excerpt(target, line)
        if not info['error']:
            self._show_excerpt(info, {'relpath': relpath, 'line': line,
                                      'kind': '', 'message': ''})
        return True

    def _find_item(self, path: str):
        """在树里按绝对路径找节点(逐层深入,避免全树递归)。"""
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _open_dir(self):
        from os_platform.openpath import open_path
        if os.path.isdir(self.root):
            open_path(self.root)
