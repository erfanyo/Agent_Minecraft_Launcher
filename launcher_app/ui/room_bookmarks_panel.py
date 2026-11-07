"""Small local invitation list; opening a bookmark never starts a connection."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel, QInputDialog, QLayout
from launcher_app.core.i18n import t
from launcher_app.ui.ui_notifications import inline_warning
from launcher_app.ui.ui_style import set_style, card_btn_style


class RoomBookmarksPanel(QWidget):
    def __init__(self, store, *, current_invitation, activate, parent=None):
        super().__init__(parent)
        self.store, self.current_invitation, self.activate = store, current_invitation, activate
        self._active = False
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        row = QHBoxLayout()
        self.choice = QComboBox();self.choice.setObjectName('roomBookmarks')
        self.choice.setProperty('ai_pin_sensitive', True)
        row.addWidget(QLabel(t('房间收藏')));row.addWidget(self.choice, 1)
        layout.addLayout(row)
        controls = QHBoxLayout()
        self.open_button = QPushButton(t('加入收藏房间'))
        self.save_button = QPushButton(t('收藏当前房间'))
        self.rename_button = QPushButton(t('修改备注'))
        self.remove_button = QPushButton(t('移除收藏'))
        for button in (self.open_button, self.save_button, self.rename_button, self.remove_button):
            controls.addWidget(button);set_style(button, card_btn_style)
        layout.addLayout(controls)
        hint = QLabel(t('收藏含房间凭证，仅保存在本机；备注不改变房间码，也不代表房间永久在线。'))
        hint.setWordWrap(True);layout.addWidget(hint)
        self.choice.currentIndexChanged.connect(self._selection)
        self.open_button.clicked.connect(self._open)
        self.save_button.clicked.connect(self._save)
        self.rename_button.clicked.connect(self._rename)
        self.remove_button.clicked.connect(self._remove)
        self.refresh()

    def _guard(self, operation):
        try:
            operation()
        except Exception:
            # Never include storage contents/invitations in warnings or logs.
            inline_warning(self, t('房间收藏'), t('房间收藏读写失败，请检查本机文件权限。'))

    def refresh(self, identity=None):
        def load():
            selected = identity or getattr(self.choice.currentData(), 'identity', None)
            self.choice.blockSignals(True)
            try:
                self.choice.clear();self.choice.addItem(t('选择收藏房间'), None)
                for item in self.store.load():
                    role = t('房主') if item.role == 'host' else t('加入者')
                    self.choice.addItem(f'{item.name} · {role}', item)
                    if item.identity == selected:self.choice.setCurrentIndex(self.choice.count()-1)
            finally:
                self.choice.blockSignals(False)
            self._selection()
        self._guard(load)

    def _selection(self):
        item = self.choice.currentData()
        self.save_button.setEnabled(not self._busy and bool(self.current_invitation()))
        self.open_button.setText(t('重开收藏房间') if item and item.role == 'host' else t('加入收藏房间'))
        self.open_button.setEnabled(bool(item) and not self._active)
        self.rename_button.setEnabled(bool(item))
        self.remove_button.setEnabled(bool(item))

    def set_session(self, *, active, busy=False):
        self._active = active or busy
        self._busy = busy
        self.choice.setEnabled(not busy)
        self._selection()
        self.rename_button.setEnabled(self.rename_button.isEnabled() and not busy)
        self.remove_button.setEnabled(self.remove_button.isEnabled() and not busy)

    def _open(self):
        item = self.choice.currentData()
        if item and not self._active:self.activate(item)

    def _save(self):
        invitation = self.current_invitation()
        if not invitation:
            return
        role, code = invitation
        name, ok = QInputDialog.getText(self, t('收藏当前房间'), t('本地备注名称：'))
        if ok and name.strip():
            def save():
                item = self.store.add(name, role, code);self.refresh(item.identity)
            self._guard(save)

    def _rename(self):
        item = self.choice.currentData()
        if not item:return
        name, ok = QInputDialog.getText(self, t('修改备注'), t('本地备注名称：'), text=item.name)
        if ok and name.strip():
            self._guard(lambda: (self.store.rename(item.identity, name), self.refresh(item.identity)))

    def _remove(self):
        item = self.choice.currentData()
        if item:self._guard(lambda: (self.store.remove(item.identity), self.refresh()))
