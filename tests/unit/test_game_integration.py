"""Lifecycle cooperation through ports; never start a model or bridge thread."""
from types import SimpleNamespace
from unittest.mock import Mock
from launcher_app.ai.game_integration import GameIntegration,GameIntegrationPorts
from launcher_app.ai.in_game_ai import _in_game_ctx


def build():
    ports=GameIntegrationPorts(**{field:Mock() for field in GameIntegrationPorts.__dataclass_fields__})
    bridges=[]
    def bridge(*args,**kwargs):
        value=SimpleNamespace(start=Mock(),stop=Mock(),args=args,kwargs=kwargs)
        bridges.append(value)
        return value
    answerer=Mock(return_value=lambda *args:'reply')
    return GameIntegration(ports,bridge_factory=bridge,answerer_factory=answerer),ports,bridges,answerer


def test_off_unloads_local_engine_without_creating_bridge():
    integration,ports,bridges,_=build()
    integration.before_launch({'ai_in_game':'off'})
    integration.started('process','one',{'ai_in_game':'off'},'root','context')
    ports.stop_local_engine.assert_called_once()
    ports.skill_started.assert_called_once_with('process','one')
    ports.game_running.assert_called_once_with('process')
    assert not bridges


def test_switching_games_stops_previous_bridge_and_uses_context_snapshot():
    integration,ports,bridges,answerer=build()
    integration.started('p1','one',{'ai_in_game':'local'},'root-one','first-context')
    assert answerer.call_args.kwargs['context_provider']()=='first-context'
    integration.started('p2','two',{'ai_in_game':'cloud'},'root-two','second-context')
    bridges[0].stop.assert_called_once()
    assert bridges[1].kwargs['game_dir']=='root-two'
    assert answerer.call_args.kwargs['context_provider']()=='second-context'
    integration.stopped(0,'remaining')
    ports.game_running.assert_called_with('remaining')
    ports.game_stopped.assert_not_called()
    bridges[1].stop.assert_called_once()


def test_off_switch_stops_existing_bridge():
    integration,ports,bridges,_=build()
    integration.start_bridge('one',{'ai_in_game':'local'},'root','context')
    integration.start_bridge('two',{'ai_in_game':'off'},'root','context')
    bridges[0].stop.assert_called_once()
    assert integration.bridge is None


def test_context_provider_does_not_require_window():
    text=_in_game_ctx(None,'one',{},context_provider=lambda:'captured context')
    assert 'captured context' in text
