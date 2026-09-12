"""Exercise the configured cloud model against the read-only crash-analysis path."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    instance = sys.argv[1]
    root = Path(sys.argv[2]).resolve()
    if root.exists():
        raise ValueError('Use a new regression output directory')
    root.mkdir(parents=True)

    import ai_run
    import agent_tools
    from assistant import CLOUD_MAX_TOKENS, TOOLS
    from settings import load_settings
    from skill_manager import SkillManager

    config = load_settings()
    config.update(ai_run_timeout_seconds=240, ai_run_context_chars=64000,
                  ai_cloud_tool_log=True)

    def data_dir(sub=''):
        destination = root / 'records' / sub
        destination.mkdir(parents=True, exist_ok=True)
        return str(destination)

    ai_run.data_dir = data_dir
    allowed = {'list_instances', 'read_instance_log', 'read_crash_report',
               'list_mods', 'inspect_mod_jar', 'inspect_instance_core'}
    schemas = [schema for schema in TOOLS if schema['function']['name'] in allowed]
    fields = {schema['function']['name']:
              set(schema['function']['parameters']['properties']) for schema in schemas}
    calls = []

    def execute(name, arguments):
        if name not in allowed:
            raise ValueError('Only read-only diagnostic tools are allowed')
        if set(arguments) - fields[name]:
            raise ValueError('Undeclared arguments are not allowed')
        if name != 'list_instances' and arguments.get('instance') != instance:
            raise ValueError('The regression is restricted to the reported instance')
        result = getattr(agent_tools, name)(**arguments)
        calls.append({'name': name, 'arguments': arguments, 'result_chars': len(str(result))})
        print(len(calls), name, flush=True)
        return result

    messages = [
        {'role': 'system', 'content': '你是启动器崩溃诊断助手。本轮只读分析，不修改实例。\n' +
         '\n'.join(SkillManager(None, config).ai_hints())},
        {'role': 'user', 'content':
         f'我的游戏异常退出了（退出码 1），实例 {instance}。帮我分析原因和解决办法。'
         '请读取本轮日志和必要的 Mod 内部元数据，给出有证据的修改意见清单；不要修改文件。'},
    ]
    reply = ai_run.run(messages, config, schemas, execute, max_tokens=CLOUD_MAX_TOKENS)
    result = {'instance': instance, 'model': config.get('ai_model'),
              'initial_max_tokens': CLOUD_MAX_TOKENS, 'calls': calls, 'reply': reply,
              'empty_response_failure': '模型连续返回空正文' in reply}
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                      encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'reply'},
                     ensure_ascii=False))
    print(reply)


if __name__ == '__main__':
    main()
