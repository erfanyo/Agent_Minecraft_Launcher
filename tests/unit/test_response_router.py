from unittest.mock import patch
from launcher_app.ai.response_router import _cloud_chat, route_answer


def test_cloud_result_and_forced_tool_survive_module_split():
    settings={'ai_base_url':'http://127.0.0.1:1234/v1','ai_model':'test'}
    executor=lambda name,args:'done'
    with patch('launcher_app.ai.response_router.chat_with_tools',return_value='reply') as run:
        answer=_cloud_chat('hello',settings,context='captured context',force_tools=['send_game_command'],executor=executor)
    assert answer=='reply'
    messages, configured, tools, passed_executor=run.call_args.args
    assert messages[0]['content']=='captured context'
    assert 'send_game_command' in {row['function']['name'] for row in tools}
    assert passed_executor is executor
    assert configured['ai_model']=='test'


def test_cloud_route_does_not_construct_local_model():
    settings={'ai_base_url':'http://127.0.0.1:1234/v1','ai_model':'test','ai_strategy':'cloud_only'}
    with patch('launcher_app.ai.task_router.route',return_value={'target':'cloud'}),patch('launcher_app.ai.response_router._local_model_downloaded',return_value=False),patch('launcher_app.ai.local_ai.GrammarToolEngine') as engine,patch('launcher_app.ai.response_router.chat_with_tools',return_value='cloud answer'):
        answer=route_answer('question',settings,executor=lambda name,args:'done')
    assert answer=='cloud answer'
    engine.assert_not_called()
