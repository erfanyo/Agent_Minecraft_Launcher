"""Render isolated settings previews without accounts, model calls or downloads."""
import argparse
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--languages', nargs='+', default=['en'])
    parser.add_argument('--themes', nargs='+', choices=['light', 'dark'], default=['light', 'dark'])
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp/language-review')
    args = parser.parse_args()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import (QApplication, QLabel, QAbstractButton, QComboBox,
                                  QLineEdit, QSpinBox, QGroupBox, QScrollArea)
    from launcher_app.core import i18n
    from launcher_app.features.registry import register_all
    from launcher_app.ui.ui_tokens import set_theme_mode
    from launcher_app.ui.ui_style import refresh_theme
    from settings.center import SettingsCenter
    import paths
    app = QApplication.instance() or QApplication([])
    families = []
    for filename in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/malgun.ttf',
                     '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'):
        if Path(filename).is_file():
            identity = QFontDatabase.addApplicationFont(filename)
            families.extend(QFontDatabase.applicationFontFamilies(identity))
    if families:
        font = QFont()
        font.setFamilies(families)
        font.setPointSize(10)
        app.setFont(font)
    i18n.load_packs_from_dir(str(ROOT / 'languages'))
    args.output.mkdir(parents=True, exist_ok=True)
    settings = {'language': 'en', 'ai_configured': True, 'username': 'PreviewPlayer',
                'third_party_plugins_enabled': False, 'plugins_disabled': [],
                'game_dir': str(args.output / 'sample-game')}
    Path(settings['game_dir']).mkdir(exist_ok=True)
    results = {}
    with ExitStack() as patches:
        patches.enter_context(patch('settings.load_settings', lambda: copy.deepcopy(settings)))
        patches.enter_context(patch.object(SettingsCenter, '_refresh_java_list'))
        patches.enter_context(patch('launcher_app.extensions.plugin_manager.discover_plugins_meta', return_value={}))
        patches.enter_context(patch.object(paths, 'GAME_DIR', settings['game_dir']))
        register_all(settings)
        for language in args.languages:
            i18n.set_language(language)
            if families:
                preferred = ('Malgun' if language == 'ko' else 'Segoe UI' if language == 'ar' else '')
                ordered = sorted(families, key=lambda family: 0 if preferred and preferred in family else 1)
                font = QFont()
                font.setFamilies(ordered)
                font.setPointSize(10)
                app.setFont(font)
            app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if i18n.is_rtl() else Qt.LayoutDirection.LeftToRight)
            for theme in args.themes:
                set_theme_mode(theme)
                refresh_theme()
                current = {**settings, 'language': language}
                center = SettingsCenter(current)
                center.resize(1200, 850)
                center.show()
                app.processEvents()
                for index, name in enumerate(center.shell.menu.items()):
                    center.shell.stack.setCurrentIndex(index)
                    app.processEvents()
                    page = center.shell.stack.widget(index)
                    texts = []
                    for widget in page.findChildren(QLabel) + page.findChildren(QAbstractButton):
                        if widget.isVisible():
                            texts.append(widget.text())
                    for widget in page.findChildren(QGroupBox):
                        if widget.isVisible():
                            texts.append(widget.title())
                    for widget in page.findChildren(QComboBox):
                        if widget.isVisible():
                            texts.extend(widget.itemText(i) for i in range(widget.count()))
                    for widget in page.findChildren(QLineEdit):
                        if widget.isVisible():
                            texts.append(widget.placeholderText())
                    for widget in page.findChildren(QSpinBox):
                        if widget.isVisible():
                            texts.append(widget.suffix())
                    key = f'{language}-{theme}-{index:02}'
                    results[key] = {'page': name, 'width': center.width(), 'height': center.height(),
                                    'chinese': sorted(set(s for s in texts if re.search('[\u4e00-\u9fff]', s)))}
                    center.grab().save(str(args.output / f'{key}-top.png'))
                    scroll = page if isinstance(page, QScrollArea) else next(iter(page.findChildren(QScrollArea)), None)
                    if scroll and scroll.verticalScrollBar().maximum() > 0:
                        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                        app.processEvents()
                        center.grab().save(str(args.output / f'{key}-bottom.png'))
                center.close()
                center.deleteLater()
                app.processEvents()
    (args.output / 'review.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(results)} settings-page states to {args.output}')


if __name__ == '__main__':
    main()
