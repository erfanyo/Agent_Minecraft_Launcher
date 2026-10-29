"""Extract explicit UI arguments and apply only translations present in a reviewed pack.

No imports of application screens, model requests, or changes to user data.
"""
import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST = {'QLabel', 'QPushButton', 'QCheckBox', 'QGroupBox', 'QRadioButton', 'SettingsSection',
         'addRow', 'add_section', 'setWindowTitle', 'setPlaceholderText', 'setToolTip',
         'setText', 'setInformativeText', 'setDetailedText', 'setTitle', 'setStatusTip',
         'addItem', 'addAction', 'setAccessibleName', 'setAccessibleDescription', 'setSuffix',
         '_section_label', '_collapsible_group'}
MESSAGES = {'task_notice', 'task_warning', 'inline_notice', 'inline_warning',
            'task_question', 'action_question'}


def chinese(text):
    return any('\u4e00' <= char <= '\u9fff' for char in text)


def template(node, source):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value, []) if chinese(node.value) else None
    if not isinstance(node, ast.JoinedStr):
        return None
    parts, fields = [], []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(value.value.replace('{', '{{').replace('}', '}}'))
        elif isinstance(value, ast.FormattedValue):
            name = f'v{len(fields)}'
            spec = ''
            if value.format_spec:
                if not all(isinstance(n, ast.Constant) for n in value.format_spec.values):
                    return None
                spec = ':' + ''.join(n.value for n in value.format_spec.values)
            conversion = '!' + chr(value.conversion) if value.conversion >= 0 else ''
            parts.append('{' + name + conversion + spec + '}')
            fields.append((name, ast.get_source_segment(source, value.value)))
        else:
            return None
    text = ''.join(parts)
    return (text, fields) if chinese(text) else None


def targets(tree, source):
    def display_parts(node):
        result = template(node, source)
        if result:
            yield node, *result
        elif isinstance(node, ast.IfExp):
            yield from display_parts(node.body)
            yield from display_parts(node.orelse)
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                yield from display_parts(value)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            yield from display_parts(node.left)
            yield from display_parts(node.right)
        elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Dict):
            for value in node.value.values:
                yield from display_parts(value)
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else ''
        indexes = []
        if name in FIRST:
            indexes = [0]
        elif name == 'setting_switch_row':
            indexes = [0, 2]
        elif name in MESSAGES:
            indexes = [1, 2]
        elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == 'QMessageBox' and name in ('warning', 'information', 'question', 'critical'):
            indexes = [1, 2]
        elif name == 'addTab':
            indexes = [1]
        elif name == '_setup_model_combo':
            indexes = [1]
        elif name == '_component_card':
            indexes = [0, 1, 2, 3]
        elif name == 'section_title':
            indexes = [0]
        elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in ('QFileDialog', 'QInputDialog'):
            indexes = [1, 2] if call.func.value.id == 'QInputDialog' else [1, 3]
        elif name in ('setHeaderLabels', 'addItems') and call.args and isinstance(call.args[0], (ast.List, ast.Tuple)):
            for node in call.args[0].elts:
                result = template(node, source)
                if result:
                    yield node, *result
        for index in indexes:
            if index < len(call.args):
                node = call.args[index]
                yield from display_parts(node)


def scan(root=ROOT):
    files = [root / 'main.py', *(root / 'launcher_app/ui').glob('*.py'),
             *(root / 'launcher_app/ai').glob('*.py'), *(root / 'settings').glob('*.py'),
             *(root / 'launcher_app/features').glob('*.py'), *(root / 'launcher_app/servers').glob('*.py')]
    # These modules construct shared controls outside ui/.
    files += [root / 'launcher_app/instances/game_launch_service.py',
              root / 'launcher_app/extensions/skill_manager.py']
    for path in files:
        source = path.read_text(encoding='utf-8-sig')
        tree = ast.parse(source)
        yield path, source, tree, list(targets(tree, source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path)
    parser.add_argument('--apply', type=Path)
    args = parser.parse_args()
    pack = json.loads(args.apply.read_text(encoding='utf-8'))['pack'] if args.apply else {}
    catalog = {}
    changes = {}
    for path, source, tree, nodes in scan():
        offsets = [0]
        for line in source.encode('utf-8').splitlines(keepends=True):
            offsets.append(offsets[-1] + len(line))
        edits = {}
        for node, text, fields in nodes:
            catalog.setdefault(text, []).append(f'{path.relative_to(ROOT).as_posix()}:{node.lineno}')
            if text not in pack:
                continue
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            replacement = 't(' + repr(text) + ')'
            if fields:
                replacement += '.format(' + ', '.join(f'{key}=({value})' for key, value in fields) + ')'
            edits[(start, end)] = replacement.encode('utf-8')
        if not edits:
            continue
        encoded = source.encode('utf-8')
        for (start, end), replacement in sorted(edits.items(), reverse=True):
            encoded = encoded[:start] + replacement + encoded[end:]
        result = encoded.decode('utf-8')
        has_import = any(isinstance(n, ast.ImportFrom) and n.module == 'launcher_app.core.i18n' and
                         any(alias.name == 't' for alias in n.names) for n in tree.body)
        if not has_import:
            # Insert after future imports (when present), preserving module docstrings.
            imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            regular = next((n for n in imports if not isinstance(n, ast.ImportFrom) or n.module != '__future__'), None)
            if regular is None:
                regular = next(n for n in tree.body if not (
                    isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
                    and not (isinstance(n, ast.ImportFrom) and n.module == '__future__'))
            lines = result.splitlines(keepends=True)
            lines.insert(regular.lineno - 1, 'from launcher_app.core.i18n import t\n')
            result = ''.join(lines)
        compile(result, str(path), 'exec')
        path.write_text(result, encoding='utf-8')
        changes[str(path.relative_to(ROOT))] = len(edits)
    if args.export:
        args.export.write_text(json.dumps([{'zh': key, 'references': refs} for key, refs in sorted(catalog.items())],
                                         ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'source_count': len(catalog), 'changed': changes}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
