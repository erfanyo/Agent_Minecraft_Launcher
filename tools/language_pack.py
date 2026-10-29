"""Export actual t() sources and audit a language pack without calling any model."""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher_app.core.strings_table import STRINGS

PLACEHOLDER = re.compile(r'(?<!\{)\{[A-Za-z_][\w.]*(?:![rsa])?(?::[^{}]*)?\}(?!\})|%(?:\([\w]+\))?[sdif]')


def catalog(root=ROOT):
    entries = {zh: en for zh, en in STRINGS.values()}
    references = {}
    # Pure-data command tables: labels/descriptions are translated, executable
    # command templates and category identifiers remain unchanged.
    from launcher_app.ai.command_templates import BUCKET_NAME, BUCKET_TEMPLATES, COMMAND_TEMPLATES
    data_strings = set(BUCKET_NAME.values())
    for table in [COMMAND_TEMPLATES, *BUCKET_TEMPLATES.values()]:
        for category, rows in table.items():
            data_strings.add(category)
            for title, command, descriptions in rows:
                data_strings.add(title)
                data_strings.update(descriptions)
    for text in data_strings:
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            entries.setdefault(text, '')
            references[text] = ['launcher_app/ai/command_templates.py']
    paths = [root / 'main.py', *(root / 'launcher_app').rglob('*.py'), *(root / 'settings').glob('*.py')]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't' and node.args):
                continue
            try:
                key = ast.literal_eval(node.args[0])
            except (ValueError, TypeError):
                continue
            english = ''
            if isinstance(key, tuple):
                key, english = key[:2]
            if not isinstance(key, str):
                continue
            if key in STRINGS:
                key, english = STRINGS[key]
            elif len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                english = node.args[1].value
            if not any('\u4e00' <= char <= '\u9fff' for char in key):
                continue
            if english or key not in entries:
                entries[key] = english
            references.setdefault(key, []).append(f'{path.relative_to(root).as_posix()}:{node.lineno}')
    return [{'zh': zh, 'en': en, 'references': references.get(zh, [])} for zh, en in sorted(entries.items())]


def audit(entries, pack):
    missing, invalid = [], []
    for item in entries:
        key = item['zh']
        value = pack.get(key)
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
        elif Counter(PLACEHOLDER.findall(key)) != Counter(PLACEHOLDER.findall(value)):
            invalid.append(key)
    return {'source_count': len(entries), 'translated_count': len(entries) - len(missing),
            'missing': missing, 'placeholder_mismatches': invalid,
            'scope': 'Registered t() strings only; hardcoded UI text and dynamic messages are not counted.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, help='Write source catalog (no model calls).')
    parser.add_argument('--audit', type=Path, help='Check a language pack against current sources.')
    args = parser.parse_args()
    entries = catalog()
    if args.export:
        args.export.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.audit:
        data = json.loads(args.audit.read_text(encoding='utf-8'))
        report = audit(entries, data['pack'])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(bool(report['missing'] or report['placeholder_mismatches']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
