"""Bounded-by-progress agent loop and incremental, opt-out local run records."""
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone

import requests
from log_privacy import redact
from paths import data_dir


def compact_history(messages, budget):
    """Reduce bulky observations without dropping requests or tool-call pairs.

    This is an excerpt, not a semantic summary. Keep all mutation arguments and
    user constraints verbatim; never reinterpret an omitted result as success.
    """
    working = [dict(message) for message in messages]
    protected = set()
    # Fresh generic results have not yet been read by the model. Do not cut them.
    for index in range(len(working) - 1, -1, -1):
        if working[index].get('role') != 'tool':
            break
        protected.add(index)
    calls = {call.get('id'): call.get('function', {}).get('name')
             for message in working for call in (message.get('tool_calls') or [])}
    for index, message in enumerate(working):
        if message.get('role') != 'tool':
            continue
        name = calls.get(message.get('tool_call_id'))
        if name == 'inspect_mod_jar':
            try:
                report = json.loads(message.get('content') or '')
                if isinstance(report, dict) and 'metadata_summary' in report:
                    report.pop('metadata', None)
                    report['metadata_view'] = '结构化声明完整保留；需要原文时用 full 视图重读。'
                    message['content'] = json.dumps(report, ensure_ascii=False)
                    protected.add(index)  # Never turn dependency JSON into a head/tail excerpt.
            except (ValueError, TypeError):
                pass
        elif name in ('snapshot_instance', 'restore_instance_snapshot', 'set_mod_enabled',
                      'replace_mod_version'):
            protected.add(index)  # Retain exact recovery locations and mutation outcomes.
    for message in working:
        for field in ('reasoning_content', 'reasoning', 'reasoning_details'):
            message.pop(field, None)
    for limit in (4000, 1200, 300):
        if len(json.dumps(working, ensure_ascii=False)) <= budget:
            break
        for index, message in enumerate(working):
            content = message.get('content')
            if index not in protected and message.get('role') == 'tool' and isinstance(content, str) and len(content) > limit:
                head = limit // 2
                message['content'] = (content[:head] +
                    '\n[旧工具输出已节选；省略部分不代表成功。需要时针对缺失证据重新查询，勿重复写操作。]\n' +
                    content[-head:])
    return working


def recovery_request_messages(messages, attempt):
    """Add a transient instruction after an empty or visibly truncated response."""
    if not attempt:
        return messages
    directive = (
        '\n【截断恢复】上一响应没有可见正文，或正文因长度限制未完整收尾。不要从头复盘，不要扩展分析。'
        '直接依据已有用户约束和工具结果：若还缺一项关键证据，只调用对应工具；否则立即输出不超过'
        + ('800' if attempt == 1 else '500') +
        '字的可见结论。禁止再次只返回内部推理。已完成的写操作不得重放。')
    outgoing = [dict(message) for message in messages]
    for message in outgoing:
        if message.get('role') == 'system' and isinstance(message.get('content'), str):
            message['content'] += directive
            break
    else:
        outgoing.insert(0, {'role': 'system', 'content': directive.lstrip()})
    return outgoing


class RunLog:
    def __init__(self, settings, messages):
        self.settings = settings
        self.id = uuid.uuid4().hex
        self.path = None
        self.error = None
        if settings.get('ai_cloud_tool_log', True):
            self.path = os.path.join(data_dir('ai_runs'), self.id + '.jsonl')
        from ai_training_log import _user_text
        self.write('start', model=settings.get('ai_model'), user=_user_text(messages),
                   verification='not_verified')

    def write(self, event, **values):
        if not self.path or self.error:
            return
        row = redact(dict(schema='amcl.agent-run.v1', run_id=self.id,
                          time=datetime.now(timezone.utc).isoformat(), event=event, **values), self.settings)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'a', encoding='utf-8') as file:
                file.write(json.dumps(row, ensure_ascii=False) + '\n')
                file.flush()
        except OSError as exc:
            self.error = type(exc).__name__


def run(messages, settings, tools, executor, max_rounds=None, on_tool=None,
        on_user_ask=None, return_messages=False, cancel_event=None, max_tokens=2048,
        stop_after_first_tool=False):
    # max_rounds is retained only for caller compatibility; no tool-count ceiling.
    working = list(messages)
    log = RunLog(settings, messages)
    started = time.monotonic()
    seconds = max(1, int(settings.get('ai_run_timeout_seconds', 1800)))
    context_chars = max(1000, int(settings.get('ai_run_context_chars', 240000)))
    seen = {}
    recent_probes = []
    stalled = 0
    rounds = calls = 0
    empty_responses = 0
    partial_reply = ''
    response_tokens = max_tokens
    usage = {'prompt_tokens': 0, 'completion_tokens': 0}
    reason = 'error'
    reply = ''
    audit_calls = []

    def boundary():
        if cancel_event is not None and cancel_event.is_set():
            return 'cancelled'
        if time.monotonic() - started >= seconds:
            return 'time_budget'
        return None

    try:
        while True:
            reason = boundary()
            if not reason and len(json.dumps(working, ensure_ascii=False)) > context_chars * 0.8:
                compacted = compact_history(working, int(context_chars * 0.65))
                if compacted != working:
                    log.write('context_checkpoint', messages=working)
                    log.write('context_compacted',
                              before_chars=len(json.dumps(working, ensure_ascii=False)),
                              after_chars=len(json.dumps(compacted, ensure_ascii=False)))
                    working = compacted
                if len(json.dumps(working, ensure_ascii=False)) > context_chars:
                    reason = 'context_budget'
            if reason:
                break
            body = {'model': settings['ai_model'],
                    'messages': recovery_request_messages(working, empty_responses),
                    'max_tokens': response_tokens}
            if empty_responses:
                # DeepSeek thinking mode is enabled by default. Increasing max_tokens after
                # a reasoning-only truncation merely gives it more private reasoning space;
                # the real run observed 15k -> 29k -> 57k reasoning characters and no
                # visible content. Recovery must switch thinking off for this one request.
                body['thinking'] = {'type': 'disabled'}
            if tools:
                body['tools'] = tools
            headers = {'Content-Type': 'application/json'}
            if settings.get('ai_api_key'):
                headers['Authorization'] = 'Bearer ' + settings['ai_api_key']
            response = requests.post(settings['ai_base_url'].rstrip('/') + '/chat/completions',
                                     headers=headers, json=body, timeout=(15, 180))
            response.raise_for_status()
            payload = response.json()
            choice = payload['choices'][0]
            msg = choice['message']
            rounds += 1
            for key in usage:
                usage[key] += int((payload.get('usage') or {}).get(key) or 0)
            working.append(msg)
            log.write('model', round=rounds, message=msg, usage=payload.get('usage'),
                      finish_reason=choice.get('finish_reason'))
            batch = msg.get('tool_calls') or []
            if not batch:
                content = str(msg.get('content') or '')
                truncated = choice.get('finish_reason') == 'length'
                if not content.strip() or truncated:
                    # Empty and length-truncated responses are not task completion.
                    # Retry the same history so completed tools are not replayed.
                    working.pop()
                    empty_responses += 1
                    if content.strip():
                        partial_reply = content
                    reason = boundary()
                    if reason:
                        break
                    if empty_responses > 2:
                        reason = 'response_truncated' if partial_reply else 'empty_response'
                        break
                    # The UI historically starts cloud turns at 1024 tokens. Capping retries
                    # at four times that value left reasoning models stuck at 4096: they could
                    # repeatedly exhaust the whole response in reasoning_content and never emit
                    # a tool call or user-visible answer. Grow independently of the initial cap.
                    response_tokens = min(max(response_tokens * 2, 8192), 32768)
                    log.write('retry', reason='response_truncated' if truncated else 'empty_response',
                              attempt=empty_responses,
                              max_tokens=response_tokens,
                              thinking='disabled',
                              previous_finish_reason=choice.get('finish_reason'),
                              previous_reasoning_chars=len(str(msg.get('reasoning_content') or '')))
                    continue
                reason = boundary() or 'model_finished'
                reply = msg.get('content') or ''
                break
            empty_responses = 0
            repeated = True
            for call in batch:
                name = call['function']['name']
                reason = reason or boundary()
                args = {}
                executed = False
                tick = time.monotonic()
                try:
                    args = json.loads(call['function'].get('arguments') or '{}')
                    if not isinstance(args, dict):
                        raise ValueError('工具参数必须是对象')
                    if reason:
                        result = '未执行：任务已停止。'
                    else:
                        log.write('tool_start', call_id=call['id'], name=name, arguments=args)
                        executed = True
                        if name == 'ask_user':
                            if on_user_ask:
                                result = on_user_ask(args.get('question', ''), args.get('options') or [])
                            else:
                                result = '需要用户补充信息，当前通道不支持交互。'
                                reason = 'needs_input'
                        else:
                            result = executor(name, args)
                except Exception as exc:
                    result = f'工具执行失败:{type(exc).__name__}: {exc}'
                result = str(result)
                calls += int(executed)
                signature = hashlib.sha256(json.dumps([name, args, result], sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()
                probe = hashlib.sha256(json.dumps([name, args], sort_keys=True,
                                                  ensure_ascii=False).encode()).hexdigest()
                repeated = repeated and signature in seen
                seen[signature] = True
                if executed:
                    recent_probes.append(probe)
                    del recent_probes[:-6]
                log.write('tool_result', call_id=call['id'], name=name, arguments=args,
                          result=result, executed=executed, elapsed_seconds=time.monotonic()-tick)
                audit_calls.append({'name': name, 'arguments': args, 'result': result})
                working.append({'role': 'tool', 'tool_call_id': call['id'], 'content': result})
                if on_tool:
                    on_tool(name, args, result)
                if executed and result.startswith('用户取消了这项操作，未做任何修改。'):
                    reason = boundary() or 'action_declined'
                if executed and stop_after_first_tool:
                    reason = reason or 'probe_complete'
            stalled = stalled + 1 if repeated else 0
            if reason:
                break
            # Detect a model re-testing the same one or two calls even if
            # volatile fields in their results defeat exact-result matching.
            if len(recent_probes) == 6 and len(set(recent_probes)) <= 2:
                reason = 'tool_loop'
                break
            if stalled >= 3:
                reason = 'stalled'
                break
    except Exception as exc:
        reason = 'error'
        log.write('error', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        log.write('finish', reason=reason, rounds=rounds, tool_calls=calls,
                  elapsed_seconds=time.monotonic()-started, usage=usage,
                  verification='not_verified', reply=reply)
        try:
            import ai_training_log
            ai_training_log.append(settings, messages, audit_calls, reply or str(reason))
        except Exception:
            pass
    if reason == 'probe_complete':
        reply = '工具调用自测已取得结果。'
    elif reason != 'model_finished':
        labels = {'cancelled': '你已停止任务', 'stalled': '连续三轮重复操作且结果不变，已暂停',
                  'action_declined': '你取消了这项操作，本轮任务已暂停，不会反复请求同一授权',
                  'tool_loop': '反复测试同一组工具，未取得新进展，已暂停',
                  'time_budget': '达到本次时间预算，已暂停',
                  'context_budget': '压缩旧工具输出后仍超过上下文预算，已暂停；请开启新对话并提供目标、约束、已做修改和待验证事项',
                  'needs_input': '需要你补充信息，已暂停',
                  'response_truncated': '模型连续返回未完整收尾的正文，重试两次后仍被截断，已暂停',
                  'empty_response': '模型连续返回空正文且未调用工具，重试两次后仍无法继续，已暂停'}
        reply = labels.get(reason, '任务已暂停') + '。已完成的操作不会自动撤销，可查看操作记录后继续。'
        if reason == 'response_truncated' and partial_reply:
            reply += '\n\n最后一次未完整答复：\n' + partial_reply
    if log.error:
        reply += '\n⚠ 本次详细记录写入失败，请检查磁盘空间和目录权限。'
    return (reply, working) if return_messages else reply
