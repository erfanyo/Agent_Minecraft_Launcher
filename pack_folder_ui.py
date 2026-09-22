# -*- coding: utf-8 -*-
"""「内容包目录」通用面板(插件实例分区共用)。

一个面板 = 一个目录:列出内容包、导入(文件/文件夹/zip,支持拖进来)、打开目录、
删除。YSM 皮肤、TACZ 枪包、Create 原理图、车万女仆模型包、Hotai 补丁都用它,
差别只在标题、目录名、扩展名和一句提示语——所以这些都不写进核心逻辑,由插件传进来。

放在核心的原因:插件之间不能互相 import,共享控件只能留在核心(见 docs/PLUGIN_IDEAS.md)。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

import pack_folder
from ui_style import (card_btn_style, danger_color, hint_style, list_style,
                      muted_color, refresh_widget, set_style)


def _danger_btn_style() -> str:
    """危险动作按钮(删除):用主题的警示色,不写死颜色。"""
    return f"QPushButton{{color:{danger_color()};}}"


class PackDropList(QListWidget):
    """能接住拖进来文件的列表(拖放 = 导入,和「导入」按钮同一条路径)。"""

    def __init__(self, on_drop=None, parent=None):
        super().__init__(parent)
        self._on_drop = on_drop
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event):
        if self._on_drop is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._on_drop is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self._on_drop is None or not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
        event.acceptProposedAction()
        if paths:
            self._on_drop(paths)


class PackFolderPanel(QWidget):
    """一个内容包目录的管理面板。

    参数:
        folder   —— 要管理的目录(绝对路径;不存在时导入会自动创建)
        title    —— 面板顶部标题
        hint     —— 底部说明(教用户这个目录是干什么的)
        exts     —— 单文件导入/列表要认的扩展名;留空表示不限
        unit     —— 计数单位,``个`` / ``张`` / ``套``
        open_label / import_label —— 按钮文案,不同 mod 叫法不一样
        recursive —— 递归列子目录里的文件(只读目录用,如 ``hotai/``)
        read_only —— 不给导入/删除(目录是 mod 自己生成的,写进去没意义还危险)
    """

    def __init__(self, folder: str, *, title: str = '', hint: str = '', exts=(),
                 unit: str = '个', open_label: str = '打开目录',
                 import_label: str = '导入文件…', on_status=None,
                 open_dir=None, recursive: bool = False,
                 read_only: bool = False, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.exts = tuple(exts or ())
        self.unit = unit
        self.recursive = recursive
        self.read_only = read_only
        self._on_status = on_status
        self._open_dir = open_dir

        layout = QVBoxLayout(self)
        if title:
            heading = QLabel(title)
            heading.setStyleSheet('font-size: 14px;')
            layout.addWidget(heading)

        self.summary = QLabel('')
        self.summary.setStyleSheet(hint_style())
        layout.addWidget(self.summary)

        self.list = PackDropList(on_drop=None if read_only else self.import_paths)
        set_style(self.list, list_style)
        if not read_only:
            self.list.setToolTip('可以直接把文件或压缩包拖到这里导入')
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        open_btn = QPushButton(open_label)
        refresh_btn = QPushButton('刷新')
        open_btn.clicked.connect(self.open_folder)
        refresh_btn.clicked.connect(self.reload)
        for button in (open_btn, refresh_btn):
            set_style(button, card_btn_style)
            button.setMinimumHeight(30)
        row.addWidget(open_btn)
        row.addWidget(refresh_btn)
        if not read_only:
            # 一个文件夹一个包(枪包/模型包)是常态,所以导入文件与导入文件夹并排给
            import_btn = QPushButton(import_label)
            folder_btn = QPushButton('导入文件夹…')
            delete_btn = QPushButton('删除所选…')
            import_btn.clicked.connect(self.choose_files)
            folder_btn.clicked.connect(self.choose_folder)
            delete_btn.clicked.connect(self.delete_selected)
            for button in (import_btn, folder_btn):
                set_style(button, card_btn_style)
                button.setMinimumHeight(30)
            set_style(delete_btn, _danger_btn_style)
            refresh_widget(delete_btn)
            delete_btn.setMinimumHeight(30)
            row.insertWidget(0, import_btn)
            row.insertWidget(1, folder_btn)
            row.addStretch()
            row.addWidget(delete_btn)
        else:
            row.addStretch()
        layout.addLayout(row)

        if hint:
            tip = QLabel(hint)
            tip.setStyleSheet(hint_style())
            tip.setWordWrap(True)
            layout.addWidget(tip)

        self.reload()

    # ---------- 列表 ----------
    def reload(self):
        """重新扫目录(导入/删除/打开面板时都会走这里)。"""
        if self.recursive:
            entries = pack_folder.scan_tree(self.folder, exts=self.exts)
        else:
            entries = pack_folder.scan(self.folder, exts=self.exts)
        self.list.clear()
        for entry in entries:
            label = entry['name']
            if entry['is_dir']:
                label += f"   （目录 · {entry['file_count']} 个文件）"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry['path'])
            detail = (f"{entry['name']}\n{pack_folder.human_size(entry['size'])}"
                      f" · {entry['file_count']} 个文件")
            item.setToolTip(detail)
            self.list.addItem(item)
        if not entries:
            empty = ('（这个目录还没有内容）' if self.read_only
                     else '（这里还是空的,点「导入文件…」或把文件拖进来）')
            placeholder = QListWidgetItem(empty)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setForeground(QColor(muted_color()))
            self.list.addItem(placeholder)
        self.summary.setText(pack_folder.summarize(entries, self.unit))
        return entries

    def selected_paths(self) -> list:
        return [str(item.data(Qt.ItemDataRole.UserRole))
                for item in self.list.selectedItems()
                if item.data(Qt.ItemDataRole.UserRole)]

    # ---------- 操作 ----------
    def open_folder(self):
        import os
        if self._open_dir is not None:
            self._open_dir(self.folder)
            return
        try:
            os.makedirs(self.folder, exist_ok=True)
            from os_platform.openpath import open_path
            open_path(self.folder)
        except Exception:
            pass

    def choose_files(self):
        """选文件导入(压缩包也在这里选:很多皮肤/枪包就是一个 zip)。"""
        patterns = ' '.join(f'*{e}' for e in self.exts) if self.exts else ''
        filters = f'内容包 ({patterns})' if patterns else '所有文件 (*)'
        if patterns:
            filters += ';;压缩包 (*.zip);;所有文件 (*)'
        paths, _selected = QFileDialog.getOpenFileNames(self, '选择要导入的文件', '', filters)
        if paths:
            self.import_paths(paths)

    def choose_folder(self):
        """选一个文件夹导入(「一个文件夹一个包」的 mod 用这条)。"""
        folder = QFileDialog.getExistingDirectory(self, '选择要导入的文件夹')
        if folder:
            self.import_paths([folder])

    def import_paths(self, sources):
        outcome = pack_folder.import_sources(self.folder, sources, exts=self.exts)
        self.reload()
        text = pack_folder.import_summary(outcome)
        if self._on_status is not None:
            self._on_status(text)
        errors = outcome.get('errors') or []
        if errors:
            detail = '\n'.join(f'{name}:{why}' for name, why in errors[:8])
            QMessageBox.warning(self, '部分文件没导入成功', f'{text}\n\n{detail}')
        elif not outcome.get('added'):
            QMessageBox.information(
                self, '没有导入任何东西',
                f'{text}\n\n常见原因:同名文件已经存在(不会覆盖),'
                f'或者选的文件不是这个目录该放的类型。')

    def delete_selected(self):
        paths = self.selected_paths()
        if not paths:
            QMessageBox.information(self, '没有选中', '先在列表里选中要删除的内容包。')
            return
        import os
        names = '、'.join(sorted(os.path.basename(p) for p in paths)[:5])
        if QMessageBox.question(
                self, '确认删除',
                f'确定删除这 {len(paths)} 项吗?\n\n{names}\n\n删除后无法恢复。'
        ) != QMessageBox.StandardButton.Yes:
            return
        outcome = pack_folder.remove_paths(paths)
        self.reload()
        text = f"已删除 {len(outcome['removed'])} 项"
        errors = outcome.get('errors') or []
        if errors:
            text += f",{len(errors)} 项失败"
        if self._on_status is not None:
            self._on_status(text)
        if errors:
            detail = '\n'.join(f'{name}:{why}' for name, why in errors[:8])
            QMessageBox.warning(self, '部分内容没删掉', f'{text}\n\n{detail}')
