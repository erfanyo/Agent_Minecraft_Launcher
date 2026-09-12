import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from ai_run import compact_history, recovery_request_messages, run


def response(n=None):
    msg = {'role': 'assistant', 'content': '完成' if n is None else None}
    if n is not None:
        msg['tool_calls'] = [{'id': str(n), 'type': 'function', 'function':
                             {'name': 'inspect', 'arguments': json.dumps({'n': n})}}]
    result = Mock()
    result.json.return_value = {'choices': [{'message': msg}], 'usage': {'prompt_tokens': 2}}
    return result


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = patch('ai_run.data_dir', return_value=self.temp.name)
        p.start()
        self.addCleanup(p.stop)
        p = patch('ai_training_log.append')
        p.start()
        self.addCleanup(p.stop)
        self.settings = {'ai_model': 'test', 'ai_base_url': 'https://example.invalid', 'ai_api_key': 'secret-test-key'}

    def events(self):
        return [json.loads(x) for x in next(Path(self.temp.name).glob('*.jsonl')).read_text(encoding='utf-8').splitlines()]

    def test_beyond_old_limit(self):
        with patch('ai_run.requests.post', side_effect=[response(n) for n in range(15)] + [response()]):
            self.assertEqual(run([], self.settings, [], lambda n, a: str(a), max_rounds=2), '完成')
        last = self.events()[-1]
        self.assertEqual(last['tool_calls'], 15)
        self.assertEqual(last['reason'], 'model_finished')
        self.assertEqual(last['verification'], 'not_verified')

    def test_stagnation(self):
        with patch('ai_run.requests.post', return_value=response(1)):
            self.assertIn('重复', run([], self.settings, [], lambda n, a: 'same'))
        self.assertEqual(self.events()[-1]['reason'], 'stalled')

    def test_empty_response_after_four_tools_retries_without_replaying(self):
        empty = response()
        choice = empty.json.return_value['choices'][0]
        choice['message']['content'] = ''
        choice['message']['reasoning_content'] = 'Still investigating'
        choice['finish_reason'] = 'length'
        execute = Mock(return_value='result')
        replies = [response(n) for n in range(4)] + [empty, response(4), response()]
        with patch('ai_run.requests.post', side_effect=replies) as request:
            self.assertEqual(run([], self.settings, [], execute), '完成')
        self.assertEqual(execute.call_count, 5)
        self.assertEqual(request.call_args_list[5].kwargs['json']['max_tokens'], 8192)
        self.assertEqual(request.call_args_list[5].kwargs['json']['thinking'], {'type': 'disabled'})
        self.assertEqual(self.events()[-1]['reason'], 'model_finished')
        self.assertTrue(any(e.get('finish_reason') == 'length' for e in self.events()))

    def test_ui_sized_reasoning_retries_escape_old_4096_cap(self):
        empty = response()
        choice = empty.json.return_value['choices'][0]
        choice['message']['content'] = ''
        choice['message']['reasoning_content'] = 'unfinished reasoning'
        choice['finish_reason'] = 'length'
        with patch('ai_run.requests.post', side_effect=[empty, empty, response()]) as request:
            self.assertEqual(run([], self.settings, [], Mock(), max_tokens=1024), '完成')
        sizes = [call.kwargs['json']['max_tokens'] for call in request.call_args_list]
        self.assertEqual(sizes, [1024, 8192, 16384])
        self.assertNotIn('thinking', request.call_args_list[0].kwargs['json'])
        self.assertTrue(all(call.kwargs['json']['thinking'] == {'type': 'disabled'}
                            for call in request.call_args_list[1:]))
        retries = [event for event in self.events() if event['event'] == 'retry']
        self.assertEqual([event['previous_finish_reason'] for event in retries], ['length', 'length'])
        self.assertTrue(all(event['previous_reasoning_chars'] > 0 for event in retries))
        self.assertNotIn('截断恢复', request.call_args_list[0].kwargs['json']['messages'][0].get('content', ''))
        self.assertIn('截断恢复', request.call_args_list[1].kwargs['json']['messages'][0]['content'])
        self.assertIn('500', request.call_args_list[2].kwargs['json']['messages'][0]['content'])

    def test_recovery_directive_is_transient(self):
        messages = [{'role': 'system', 'content': 'original'}, {'role': 'user', 'content': 'task'}]
        outgoing = recovery_request_messages(messages, 1)
        self.assertIn('截断恢复', outgoing[0]['content'])
        self.assertEqual(messages[0]['content'], 'original')

    def test_persistent_empty_response_has_visible_failure(self):
        empty = response()
        empty.json.return_value['choices'][0]['message']['content'] = '  '
        with patch('ai_run.requests.post', return_value=empty) as request:
            reply, history = run([], self.settings, [], Mock(), return_messages=True)
        self.assertEqual(request.call_count, 3)
        self.assertIn('空正文', reply)
        self.assertEqual(history, [])
        self.assertEqual(self.events()[-1]['reason'], 'empty_response')

    def test_nonempty_length_response_retries_until_complete(self):
        partial = response()
        choice = partial.json.return_value['choices'][0]
        choice['message']['content'] = '证据显示核心完整，但还需检查'
        choice['finish_reason'] = 'length'
        complete = response()
        complete.json.return_value['choices'][0]['message']['content'] = '核心完整，应继续检查模组加载。'
        with patch('ai_run.requests.post', side_effect=[partial, complete]) as request:
            self.assertEqual(run([], self.settings, [], Mock()), '核心完整，应继续检查模组加载。')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].kwargs['json']['max_tokens'], 8192)
        retry = [event for event in self.events() if event['event'] == 'retry'][0]
        self.assertEqual(retry['reason'], 'response_truncated')

    def test_persistent_nonempty_truncation_preserves_last_partial_answer(self):
        partial = response()
        choice = partial.json.return_value['choices'][0]
        choice['message']['content'] = '尚未写完的诊断'
        choice['finish_reason'] = 'length'
        with patch('ai_run.requests.post', return_value=partial):
            reply, history = run([], self.settings, [], Mock(), return_messages=True)
        self.assertIn('未完整收尾', reply)
        self.assertIn('尚未写完的诊断', reply)
        self.assertEqual(history, [])
        self.assertEqual(self.events()[-1]['reason'], 'response_truncated')

    def test_cancel_after_tool(self):
        event = threading.Event()
        def execute(n, a):
            event.set()
            return 'done'
        with patch('ai_run.requests.post', return_value=response(1)) as request:
            run([], self.settings, [], execute, cancel_event=event)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.events()[-1]['reason'], 'cancelled')

    def test_error_keeps_partial_log(self):
        with patch('ai_run.requests.post', side_effect=[response(1), RuntimeError('network')]):
            with self.assertRaises(RuntimeError):
                run([], self.settings, [], lambda n, a: 'done')
        self.assertTrue(any(e['event'] == 'tool_result' for e in self.events()))
        self.assertEqual(self.events()[-1]['reason'], 'error')

    def test_opt_out(self):
        self.settings['ai_cloud_tool_log'] = False
        with patch('ai_run.requests.post', return_value=response()):
            run([], self.settings, [], lambda n, a: '')
        self.assertFalse(list(Path(self.temp.name).glob('*')))

    def test_context_budget(self):
        self.settings['ai_run_context_chars'] = 1000
        with patch('ai_run.requests.post') as request:
            run([{'role': 'user', 'content': 'a' * 1100}], self.settings, [], lambda n, a: '')
            request.assert_not_called()
        self.assertEqual(self.events()[-1]['reason'], 'context_budget')

    def test_resume_over_budget_keeps_constraints_and_tool_pairs(self):
        self.settings['ai_run_context_chars'] = 4000
        messages = [
            {'role': 'system', 'content': 'Keep tool permissions'},
            {'role': 'user', 'content': 'Repair demo; keep MC 1.21.1 and all mods'},
            {'role': 'assistant', 'content': 'Snapshot created; verify replacement next',
             'reasoning_content': 'private reasoning' * 1000,
             'tool_calls': [{'id': 'write1', 'type': 'function', 'function':
                             {'name': 'replace_mod_version', 'arguments': '{"version":"exact"}'}}]},
            {'role': 'tool', 'tool_call_id': 'write1', 'content': 'backup=demo/old\n' + 'x' * 1200 + '\nnot verified'},
            {'role': 'user', 'content': '继续'}]
        execute = Mock()
        with patch('ai_run.requests.post', return_value=response()) as request:
            reply, history = run(messages, self.settings, [], execute, return_messages=True)
        self.assertEqual(reply, '完成')
        sent = request.call_args.kwargs['json']['messages']
        self.assertEqual(sent[:2], messages[:2])
        self.assertEqual(sent[2]['tool_calls'], messages[2]['tool_calls'])
        self.assertEqual(sent[3]['tool_call_id'], 'write1')
        self.assertIn('backup=demo/old', sent[3]['content'])
        self.assertIn('not verified', sent[3]['content'])
        self.assertNotIn('reasoning_content', sent[2])
        self.assertIn('reasoning_content', messages[2])
        self.assertLess(len(json.dumps(history, ensure_ascii=False)), 4000)
        execute.assert_not_called()
        self.assertTrue(any(e['event'] == 'context_checkpoint' for e in self.events()))

    def test_compaction_preserves_large_user_input_and_images(self):
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'constraint' * 500},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc'}}]}]
        self.assertEqual(compact_history(messages, 1000), messages)

    def test_middle_dependency_and_recovery_survive_compaction(self):
        report = {'metadata': {'META-INF/neoforge.mods.toml': 'large description' * 1000},
                  'sha1': 'abc', 'metadata_summary': {'META-INF/neoforge.mods.toml': {
                      'status': 'parsed', 'declarations': {'dependencies': {
                          'example': [{'modId': 'essential', 'type': 'required', 'versionRange': '[2,3)'}]}}}}}
        messages = [
            {'role': 'assistant', 'tool_calls': [
                {'id': 'inspect', 'function': {'name': 'inspect_mod_jar', 'arguments': '{}'}},
                {'id': 'change', 'function': {'name': 'set_mod_enabled', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'inspect', 'content': json.dumps(report)},
            {'role': 'tool', 'tool_call_id': 'change', 'content': 'recovery-middle-' * 300},
            {'role': 'user', 'content': 'continue'}]
        compacted = compact_history(messages, 900)
        self.assertEqual(json.loads(compacted[1]['content'])['metadata_summary'], report['metadata_summary'])
        self.assertNotIn('metadata', json.loads(compacted[1]['content']))
        self.assertEqual(compacted[2], messages[2])

    def test_fresh_result_is_not_cut_before_model_reads_it(self):
        messages = [{'role': 'tool', 'tool_call_id': 'latest', 'content': 'result' * 1000}]
        self.assertEqual(compact_history(messages, 1000), messages)

    def test_no_user_channel_stops_batch(self):
        r = response(1)
        msg = r.json.return_value['choices'][0]['message']
        msg['tool_calls'][0]['function']['name'] = 'ask_user'
        msg['tool_calls'].append({'id': 'second', 'function': {'name': 'write', 'arguments': '{}'}})
        execute = Mock()
        with patch('ai_run.requests.post', return_value=r):
            _, history = run([], self.settings, [], execute, return_messages=True)
        execute.assert_not_called()
        self.assertEqual(len([m for m in history if m['role'] == 'tool']), 2)
        self.assertEqual(self.events()[-1]['reason'], 'needs_input')


if __name__ == '__main__':
    unittest.main()
