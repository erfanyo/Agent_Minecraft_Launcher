# -*- coding: utf-8 -*-
"""KubeJS 脚本查看器:树形列目录 + 展开查看脚本内容。

**为什么需要**:原先实例详情里的 KubeJS 页只有一个**文件名列表**,点开看不到内容。
而 KubeJS 恰恰是最需要「进不去游戏也要改」的东西——脚本语法错会让服务端直接
启动失败,那时唯一的排查手段就是读脚本。所以这里给一个只读查看器。

安全与实用取舍:

- **只读**,不做保存。写脚本属于「改代码」,应该有差异对比与备份,单独做(见后续)。
- **限制单文件大小**,避免有人把几百 MB 的日志塞进来把界面卡死。
- **不跟随链接**,与项目其它读目录逻辑一致。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ui_style import hint_style, list_style, muted_color, set_style

#: 单个脚本的显示上限(字符)。超过只显示开头,并明确提示。
MAX_PREVIEW_CHARS = 200_000
#: 视为「可查看文本」的后缀。
TEXT_SUFFIXES = ('.js', '.json', '.txt', '.snbt', '.properties', '.toml',
                 '.md', '.mcfunction', '.csv', '.yml', '.yaml')


def build_script_tree(root: str) -> list:
    """把 ``kubejs`` 目录扫成 ``[{'name','path','is_dir','children'}]``。

    纯函数式(只读目录),方便单测;不跟随符号链接。
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if name.startswith('.'):
            continue
        full = os.path.join(root, name)
        if os.path.islink(full):
            continue
        if os.path.isdir(full):
            out.append({'name': name, 'path': full, 'is_dir': True,
                        'children': build_script_tree(full)})
        else:
            out.append({'name': name, 'path': full, 'is_dir': False,
                        'children': []})
    return out


def is_viewable(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in TEXT_SUFFIXES


def read_script(path: str):
    """读脚本 → ``(text, truncated, error)``。任何失败都返回可展示的说明。"""
    if not path or not os.path.isfile(path):
        return '', False, '文件不存在'
    try:
        size = os.path.getsize(path)
    except OSError as error:
        return '', False, f'读取失败：{error}'
    try:
        with open(path, encoding='utf-8', errors='replace') as stream:
            text = stream.read(MAX_PREVIEW_CHARS + 1)
    except OSError as error:
        return '', False, f'读取失败：{error}'
    truncated = len(text) > MAX_PREVIEW_CHARS or size > MAX_PREVIEW_CHARS
    if truncated:
        text = text[:MAX_PREVIEW_CHARS]
    return text, truncated, ''


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
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh)
        open_btn = QPushButton('打开目录')
        open_btn.clicked.connect(self._open_dir)
        row.addWidget(self.title, 1)
        row.addWidget(refresh_btn)
        row.addWidget(open_btn)
        layout.addLayout(row)

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

    def _open_dir(self):
        from os_platform.openpath import open_path
        if os.path.isdir(self.root):
            open_path(self.root)
