# -*- coding: utf-8 -*-
"""``server.properties`` 可视化编辑对话框。

设计取舍:

- **表单化而非纯文本**:纯文本一改就错(少空格、大小写、误删 level-name),所以按
  :mod:`server_properties` 的分组渲染控件——布尔给下拉、枚举给下拉、端口/数量给
  数字框,其余给单行输入。
- **危险项要显式确认**:改 ``level-name`` / ``level-type`` 可能导致「进服发现是
  个全新空世界」,这类键改动前弹一次确认。
- **未知键也列出来**:Minecraft 与 Mod 会写自己的键,直接隐藏会让用户以为启动器
  「吃掉了配置」。它们放在「其他(未知键)」里,同样可改。
- **只交改动**:对话框只返回用户真正动过的键,避免把表单里的全量值回写(那样会把
  服务端运行时写入的新键覆盖掉)。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

import server_properties as sp
import server_properties_io as sp_io
from ui_style import hint_style, muted_color


class ServerPropertiesDialog(QDialog):
    """按分组编辑 server.properties;``changes`` 为最终要写入的键值。"""

    def __init__(self, server_root: str, parent=None):
        super().__init__(parent)
        self.server_root = server_root
        self.changes = {}
        self._editors = {}          # key -> 取值回调
        self._original = {}
        self.setWindowTitle('server.properties · 可视化编辑')
        self.resize(760, 640)
        self._original = sp_io.read_values(server_root)
        self._build()
        self._refresh_status()

    # ---------- 构建 ----------
    def _build(self):
        root = QVBoxLayout(self)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        hint = QLabel('改动保存前会先备份为 server.properties.bak；'
                      '服务端运行时不允许直接改配置。')
        hint.setWordWrap(True)
        hint.setStyleSheet(hint_style())
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self.form_host = QVBoxLayout(inner)
        self.form_host.setSpacing(10)

        known = sp.known_keys()
        for group in sp.GROUP_ORDER:
            items = [item for item in sp.CATALOG if item['group'] == group]
            present = [item for item in items
                       if item['key'] in self._original or item.get('danger')
                       or item['key'] in ('server-port', 'motd', 'online-mode')]
            if present:
                self.form_host.addWidget(self._group_box(group, present))

        # 未知键:文件里有、目录里没有。单独一组,避免「启动器把我的配置吃了」的误会。
        unknown = [(key, value) for key, value in self._original.items()
                   if key not in known]
        if unknown:
            self.form_host.addWidget(self._unknown_box(unknown))

        self.form_host.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        self.save_btn = buttons.addButton('保存', QDialogButtonBox.ButtonRole.AcceptRole)
        self.revert_btn = buttons.addButton('放弃修改',
                                            QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton('取消', QDialogButtonBox.ButtonRole.RejectRole)
        self.save_btn.clicked.connect(self._on_save)
        self.revert_btn.clicked.connect(self._on_revert)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _group_box(self, title: str, items: list) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        for item in items:
            key = item['key']
            field, getter = self._make_editor(item, self._original.get(key, ''))
            self._editors[key] = getter
            label = sp.label_for(key)
            if item.get('danger'):
                label = '⚠ ' + label
            holder = QWidget()
            column = QVBoxLayout(holder)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addWidget(field)
            if item.get('hint'):
                note = QLabel(item['hint'])
                note.setWordWrap(True)
                note.setStyleSheet(f'color:{muted_color()}; font-size:11px;')
                column.addWidget(note)
            form.addRow(label, holder)
        return box

    def _unknown_box(self, pairs: list) -> QGroupBox:
        box = QGroupBox('其他（文件里的未知键，原样保留并可直接编辑）')
        form = QFormLayout(box)
        for key, value in pairs:
            field = QLineEdit(value)
            self._editors[key] = field.text
            form.addRow(key, field)
        return box

    def _make_editor(self, item: dict, value: str):
        kind = item['type']
        key = item['key']
        if kind == sp.BOOL:
            combo = QComboBox()
            combo.addItem('开启 (true)', 'true')
            combo.addItem('关闭 (false)', 'false')
            normalised = sp.normalise_bool(value)
            if normalised is None:
                # 文件里是个不认识的写法:显式提示,不擅自改成 true/false
                combo.addItem(f'原值（无法识别）：{value}', value)
                combo.setCurrentIndex(2)
            else:
                combo.setCurrentIndex(0 if normalised == 'true' else 1)
            return combo, (lambda c=combo: c.currentData())
        if kind == sp.INT:
            spin = QSpinBox()
            spin.setRange(-2147483648, 2147483647)
            try:
                spin.setValue(int(value))
            except (TypeError, ValueError):
                spin.setValue(0)
            return spin, (lambda s=spin: str(s.value()))
        allowed = sp.ENUMS.get(key)
        if allowed:
            combo = QComboBox()
            for option in sorted(allowed):
                combo.addItem(option, option)
            index = combo.findData(value.strip().casefold())
            if index < 0:
                combo.addItem(f'原值：{value}', value)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
            return combo, (lambda c=combo: c.currentData())
        if item.get('secret'):
            secret = QLineEdit(value)
            secret.setEchoMode(QLineEdit.EchoMode.Password)
            return secret, secret.text
        plain = QLineEdit(value)
        return plain, plain.text

    # ---------- 交互 ----------
    def collect_changes(self) -> dict:
        """只返回与原始值不同的项(未改动的不写入)。"""
        out = {}
        for key, getter in self._editors.items():
            if getter is None:
                continue
            try:
                value = getter()
            except RuntimeError:
                continue
            before = self._original.get(key, '')
            kind = (sp.CATALOG_BY_KEY.get(key) or {}).get('type', sp.STR)
            if kind == sp.BOOL:
                normalised = sp.normalise_bool(value)
                if normalised is not None:
                    value = normalised
            if str(value) != str(before):
                out[key] = value
        return out

    def _refresh_status(self):
        if sp_io.server_running(self.server_root):
            self.status.setText('⛔ 服务端正在运行：现在保存会被拒绝。请先停止服务端。')
            self.save_btn.setEnabled(False)
        else:
            self.status.setText('✅ 可以保存。')
            self.save_btn.setEnabled(True)

    def _on_revert(self):
        """放弃修改:编辑期间从未写盘,所以直接关闭并返回「未改动」即可。"""
        self.changes = {}
        self.reject()

    def _on_save(self):
        changes = self.collect_changes()
        if not changes:
            self.status.setText('没有任何改动。')
            return
        dangerous = [key for key in changes if sp.is_dangerous(key)]
        if dangerous:
            names = '、'.join(sp.label_for(key) for key in dangerous)
            answer = QMessageBox.warning(
                self, '确认修改危险项',
                f'以下改动可能让服务端起不来，或生成一个全新的空世界：\n\n{names}\n\n'
                '确定要保存吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        result = sp_io.apply_update(self.server_root, changes)
        self.status.setText(('✅ ' if result['ok'] else '⛔ ') + result['message'])
        if result['ok']:
            self.changes = changes
            self.accept()


def edit_server_properties(server_root: str, parent=None):
    """便捷入口:打开对话框,返回 ``{'ok','changes','message'}``。"""
    if sp_io.server_running(server_root):
        return {'ok': False, 'changes': {}, 'message': '服务端正在运行，请先停止再修改配置。'}
    dialog = ServerPropertiesDialog(server_root, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return {'ok': accepted, 'changes': dialog.changes,
            'message': '已保存。' if accepted else '已取消，未做改动。'}
