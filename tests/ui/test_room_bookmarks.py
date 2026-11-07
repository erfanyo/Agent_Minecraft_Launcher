from types import SimpleNamespace
from unittest.mock import patch, Mock
import pytest
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QLabel, QPushButton
from PySide6.QtCore import QObject, QTimer
from launcher_app.features import lan_bridge as lan
from launcher_app.online.room_bookmarks import RoomBookmarks
from launcher_app.ui.room_bookmarks_panel import RoomBookmarksPanel


@pytest.fixture
def page(qtbot,tmp_path,monkeypatch):
    widget=QWidget();qtbot.addWidget(widget)
    layout=QVBoxLayout(widget)
    api=SimpleNamespace(get_config=lambda key,default=None:default,set_config=lambda *a:None,data_path=lambda name:str(tmp_path/name))
    monkeypatch.setattr('launcher_app.instances.instances.scan_instances',lambda:[])
    monkeypatch.setattr('settings.load_settings',lambda:{})
    monkeypatch.setattr(lan,'_terracotta_path','')
    monkeypatch.setattr(lan,'_terracotta_port',None)
    monkeypatch.setattr(lan,'_save_join_address_to_selected_instance',lambda *a:'saved')
    lan._add_terracotta_ui(layout,widget,api)
    for timer in widget.findChildren(QTimer):timer.stop()
    signals=next(child for child in widget.findChildren(QObject) if type(child).__name__=='Signals')
    return widget,signals


def test_management_merged_and_address_only_after_join(page):
    widget,signals=page
    assert not any(label.text()=='大厅管理' for label in widget.findChildren(QLabel))
    address=widget.findChild(QLineEdit,'terracottaAddress')
    assert address.isHidden()
    signals.polled.emit({'state':'host-ok','room':'U/test-code'})
    assert address.isHidden()
    signals.polled.emit({'state':'guest-ok','url':'127.0.0.1:12345'})
    assert not address.isHidden() and address.text()=='127.0.0.1:12345'
    signals.polled.emit({'state':'waiting'})
    assert address.isHidden() and address.text()==''


def test_unknown_difficulty_does_not_claim_route(page):
    widget,signals=page
    signals.polled.emit({'state':'guest-starting','difficulty':'TOUGH'})
    text=widget.findChild(QLabel,'terracottaConnection').text()
    assert '困难' in text and '不代表成功率' in text
    assert '已使用中继' not in text


def test_selecting_bookmark_does_not_connect_and_rename_keeps_code(qtbot,tmp_path):
    owner=QWidget();qtbot.addWidget(owner);store=RoomBookmarks(tmp_path/'rooms.json')
    item=store.add('Host','host','U/invitation-code');activate=Mock()
    panel=RoomBookmarksPanel(store,current_invitation=lambda:None,activate=activate,parent=owner)
    panel.choice.setCurrentIndex(1)
    activate.assert_not_called()
    assert panel.open_button.text()=='重开收藏房间'
    with patch('launcher_app.ui.room_bookmarks_panel.QInputDialog.getText',return_value=('New name',True)):
        panel._rename()
    assert store.load()[0].code==item.code
    panel._open();assert activate.call_args.args[0].role=='host'
    panel.set_session(active=True)
    assert not panel.open_button.isEnabled()


def test_retry_resets_and_reuses_last_invitation_nickname_and_nodes(page,monkeypatch,tmp_path):
    widget,signals=page
    binary=tmp_path/'terracotta.exe';binary.write_bytes(b'fake')
    calls=[]
    monkeypatch.setattr(lan,'download_terracotta',lambda *a:str(binary))
    monkeypatch.setattr(lan,'terracotta_connect',lambda *a:None)
    monkeypatch.setattr(lan,'terracotta_leave',lambda:calls.append(('reset',)))
    monkeypatch.setattr(lan,'terracotta_join',lambda code,player,nodes:calls.append(('join',code,player,list(nodes))))
    monkeypatch.setattr(lan,'terracotta_state',lambda:{'state':'guest-starting','difficulty':'MEDIUM'})
    monkeypatch.setattr('threading.Thread',lambda target,daemon:SimpleNamespace(start=target))
    join=next(button for button in widget.findChildren(QPushButton) if button.text()=='加入大厅')
    join.click()
    widget.findChild(QLineEdit,'terracottaJoinCode').setText('U/retry-private-code')
    join.click()
    assert calls==[('reset',),('join','U/retry-private-code','Player',list(lan.TERRACOTTA_PUBLIC_NODES))]
    signals.polled.emit((0, {'state':'waiting'}))
    assert join.isHidden()  # Poll from before this operation cannot reset its UI.
    signals.polled.emit({'state':'exception','type':1,'_amcl_left':True})
    retry=widget.findChild(QPushButton,'terracottaRetry')
    assert not retry.isHidden() and retry.isEnabled()
    nickname=next(edit for edit in widget.findChildren(QLineEdit) if edit.placeholderText()=='大厅昵称（给其他联机成员看）')
    nickname.setText('Changed after failure')
    retry.click()
    assert calls[2:]==calls[:2]
    signals.polled.emit({'state':'guest-ok','url':'127.0.0.1:25565'})
    assert retry.isHidden()


def test_bookmark_save_disabled_without_an_invitation(qtbot,tmp_path):
    owner=QWidget();qtbot.addWidget(owner)
    panel=RoomBookmarksPanel(RoomBookmarks(tmp_path/'rooms.json'),current_invitation=lambda:None,activate=lambda _:None,parent=owner)
    assert not panel.save_button.isEnabled()
