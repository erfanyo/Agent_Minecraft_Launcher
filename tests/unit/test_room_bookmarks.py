import os
from unittest.mock import patch
import pytest
from launcher_app.online.room_bookmarks import RoomBookmarks, validate_room, connection_difficulty
from launcher_app.core.log_privacy import redact, redact_text
from launcher_app.features import lan_bridge as lan


def test_bookmarks_round_trip_rename_keeps_invitation_and_role(tmp_path):
    store=RoomBookmarks(tmp_path/'rooms.json')
    item=store.add('Friends','host','U/test-invitation')
    renamed=store.rename(item.identity,'Weekend')
    assert renamed.code==item.code and renamed.identity==item.identity and renamed.role=='host'
    guest=store.add('Join friends','guest',item.code)
    assert len(store.load())==2
    assert item.code not in repr(item)
    if os.name=='nt': assert item.code not in store.path.read_text(encoding='utf-8')
    else: assert store.path.stat().st_mode & 0o077==0
    store.remove(guest.identity)
    assert store.load()==[renamed]


def test_damaged_file_is_not_overwritten(tmp_path):
    path=tmp_path/'rooms.json';path.write_text('broken')
    with pytest.raises(ValueError): RoomBookmarks(path).add('name','guest','U/valid-code')
    assert path.read_text()=='broken'


@pytest.mark.parametrize('code',['', ' ', 'U/code\nmore', '../not a code', 'x'*257])
def test_room_input_rejected_without_exposing_value(code):
    with pytest.raises(ValueError) as error:validate_room(code)
    if code.strip():assert code not in str(error.value)


def test_old_room_code_is_passed_only_when_requested():
    with patch.object(lan,'_terracotta_request') as request:
        lan.terracotta_host('host',[],room='U/old-code')
        assert request.call_args.args==('scanning',{'public_nodes':[],'player':'host','room':'U/old-code'})
        lan.terracotta_host('host',[])
        assert 'room' not in request.call_args.args[1]


def test_invitation_redacted_from_structured_and_labelled_logs():
    assert redact({'room':'U/private-code','name':'Friends'})['room']=='[REDACTED]'
    assert 'U/private-code' not in redact_text('GET /state/guesting?room=U/private-code&player=test')


def test_difficulty_does_not_invent_nat_or_relay():
    assert connection_difficulty({'difficulty':'TOUGH'})=='困难'
    assert connection_difficulty({'difficulty':'future-value'}) is None
    assert connection_difficulty({'nat':'symmetric'}) is None
