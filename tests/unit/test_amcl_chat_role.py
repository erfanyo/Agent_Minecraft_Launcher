from types import SimpleNamespace
import pytest
from launcher_app.ai.chat_view import ChatEntry, render_entry
from tests.unit.test_chat_view import TOKENS


def test_role_roundtrip_render_and_escaping():
    entry = ChatEntry(kind='amcl', text='<untrusted> task')
    restored = ChatEntry.from_any(entry.to_dict())
    assert restored.kind == 'amcl'
    rendered = render_entry(restored, 0, TOKENS)
    assert 'AMCL' in rendered
    assert '&lt;untrusted&gt;' in rendered
    assert '<untrusted>' not in rendered


def test_app_message_does_not_consume_draft_or_raise_priority():
    from launcher_app.ai.assistant import AIChatDock
    class StopBeforeModel(Exception):
        pass
    def trim():
        raise StopBeforeModel
    appended = []
    images = [{'path': 'unsent-image.png'}]
    dock = SimpleNamespace(settings={'ai_model': 'test'}, pending_images=images,
        _agent_running=False, _focus_mode=False, _chat_messages=[],
        _confirm_if_heavy=lambda _: True,
        _append_user=lambda text, **kw: appended.append((text, kw)),
        _append_system=lambda _: None, _trim_history=trim)
    # No input/context-pins/thumb API is supplied: application tasks must not touch them.
    with pytest.raises(StopBeforeModel):
        AIChatDock.send(dock, amcl_text='download a pack')
    assert dock.pending_images is images
    assert appended == [('download a pack', {'kind': 'amcl'})]
    assert dock._chat_messages == [{'role': 'user', 'name': 'AMCL', 'content': 'download a pack'}]


def test_application_ask_dispatches_without_replacing_input():
    from launcher_app.ai.assistant import AIChatDock
    calls = []
    dock = SimpleNamespace(send=lambda **kwargs: calls.append(kwargs))
    AIChatDock.ask(dock, 'application task')
    assert calls == [{'amcl_text': 'application task'}]
