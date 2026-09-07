"""Compact installed-resource cards; local metadata only, no network requests."""
import json
import os
import re
import threading
import zipfile
from functools import lru_cache

from PySide6.QtCore import QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QStyledItemDelegate, QStyle

CARD_ROLE = int(Qt.ItemDataRole.UserRole) + 71


def _version(value):
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        return None
    parts = tuple(map(int, value.split('.')))
    return parts + (0,) * max(0, 4 - len(parts))


def incompatible_version(current, rule):
    """Only prove simple numeric exact/Maven intervals; unknown syntax is not a warning."""
    value = _version(current)
    rule = str(rule).strip()
    if value is None:
        return False
    exact = _version(rule)
    if exact is not None:
        return value != exact
    if rule.startswith('[') and rule.endswith(']') and ',' not in rule:
        exact = _version(rule[1:-1])
        return exact is not None and value != exact
    match = re.fullmatch(r"([\[(])([\d.]*),\s*([\d.]*)([\])])", rule)
    if not match:
        return False
    left, low, high, right = match.groups()
    lo, hi = _version(low), _version(high)
    return bool((lo is not None and (value < lo or (value == lo and left == '(')))
                or (hi is not None and (value > hi or (value == hi and right == ')'))))


@lru_cache(maxsize=512)
def read_card(path, mtime, size):
    result = {"name": os.path.basename(path), "description": "", "image": b"", "formats": [], "mc": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            def read(name, limit=512_000):
                info = archive.getinfo(name)
                if info.file_size > limit:
                    raise ValueError('metadata too large')
                return archive.read(info)
            names = set(archive.namelist())
            icon = 'pack.png'
            if 'fabric.mod.json' in names:
                data = json.loads(read('fabric.mod.json'))
                result.update(name=str(data.get('name') or data.get('id') or result['name']),
                              description=str(data.get('description') or ''),
                              mc=str(data.get('depends', {}).get('minecraft', '')))
                result['formats'].append('fabric')
                icon = data.get('icon', '')
                if isinstance(icon, dict):
                    icon = next(iter(icon.values()), '')
            for filename, loader in [('META-INF/mods.toml', 'forge'), ('META-INF/neoforge.mods.toml', 'neoforge')]:
                if filename not in names:
                    continue
                import tomllib
                data = tomllib.loads(read(filename).decode('utf-8'))
                result['formats'].append(loader)
                mods = data.get('mods') or [{}]
                mod = mods[0]
                result.update(name=str(mod.get('displayName') or result['name']),
                              description=str(mod.get('description') or ''))
                icon = mod.get('logoFile') or data.get('logoFile') or icon
                for dep in data.get('dependencies', {}).get(mod.get('modId'), []):
                    if dep.get('modId') == 'minecraft':
                        result['mc'] = str(dep.get('versionRange') or '')
            if 'mcmod.info' in names and not result['formats']:
                data = json.loads(read('mcmod.info'))
                mods = data if isinstance(data, list) else data.get('modList', [])
                if mods:
                    mod = mods[0]
                    result.update(name=str(mod.get('name') or result['name']), description=str(mod.get('description') or ''))
                    icon = mod.get('logoFile') or icon
                    result['formats'].append('forge')
            if isinstance(icon, str) and icon.lstrip('/') in names:
                result['image'] = read(icon.lstrip('/'), 1_000_000)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile):
        pass
    return result


def warning(data, loader, minecraft):
    formats = data.get('formats', [])
    loader = str(loader or 'vanilla').lower()
    # Forge/NeoForge cross-loading and Quilt compatibility are not inferred here.
    if (loader == 'forge' and formats == ['fabric']) or (loader == 'fabric' and formats and 'fabric' not in formats):
        return '与当前加载器不兼容：需要 ' + '/'.join(formats)
    if loader == 'vanilla' and formats:
        return '当前是原版实例：需要 Mod 加载器'
    if len(formats) == 1 and incompatible_version(str(minecraft), data.get('mc', '')):
        return '与当前 MC 版本不兼容：需要 ' + data['mc']
    return ''


class CardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(240, 88)

    def paint(self, painter, option, index):
        from ui_style import current_color, text_color, muted_color, accent_color, warning_color
        painter.save()
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QColor(accent_color() if selected else current_color('btn_border')))
        color = QColor(accent_color())
        color.setAlpha(35 if selected else 10)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 8, 8)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        area = QRect(rect.left() + 12, rect.top() + 15, 48, 48)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, area)
        else:
            painter.setPen(QColor(muted_color()))
            painter.drawRoundedRect(area.adjusted(4, 4, -4, -4), 7, 7)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, 'M' if str(index.data()).endswith(('.jar', '.disabled')) else 'R')
        data = index.data(CARD_ROLE) or {}
        x, width = area.right() + 13, max(0, rect.width() - 88)
        title = data.get('name') or str(index.data())
        disabled = str(index.data(Qt.ItemDataRole.UserRole) or '').endswith('.disabled')
        title = ('已禁用 · ' if disabled else '') + title
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(muted_color() if disabled else text_color()))
        painter.drawText(QRect(x, rect.top()+9, width, 24), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, width))
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(muted_color()))
        description = ' '.join(str(data.get('description') or index.data()).split())
        painter.drawText(QRect(x, rect.top()+34, width, 20), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(description, Qt.TextElideMode.ElideRight, width))
        if data.get('warning'):
            painter.setPen(QColor(warning_color()))
            painter.drawText(QRect(x, rect.top()+56, width, 20), Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(data['warning'], Qt.TextElideMode.ElideRight, width))
        painter.restore()


class CardLoader(QObject):
    ready = Signal(int, object)

    def __init__(self, widget):
        super().__init__(widget)
        self.widget = widget
        self.generation = 0
        widget.setItemDelegate(CardDelegate(widget))
        self.ready.connect(self.apply)

    def refresh(self, directory, loader='', minecraft=''):
        self.generation += 1
        generation = self.generation
        files = [str(self.widget.item(i).data(Qt.ItemDataRole.UserRole) or self.widget.item(i).text()) for i in range(self.widget.count())]
        def work():
            rows = []
            for filename in files:
                if generation != self.generation:
                    return
                path = os.path.join(directory, filename)
                try:
                    stat = os.stat(path)
                    data = dict(read_card(path, stat.st_mtime_ns, stat.st_size))
                    data['warning'] = warning(data, loader, minecraft)
                    rows.append((filename, data))
                except OSError:
                    pass
            try:
                self.ready.emit(generation, rows)
            except RuntimeError:
                pass  # Page was closed while reading.
        threading.Thread(target=work, daemon=True).start()

    def apply(self, generation, rows):
        if generation != self.generation:
            return
        by_name = dict(rows)
        for i in range(self.widget.count()):
            item = self.widget.item(i)
            data = by_name.get(str(item.data(Qt.ItemDataRole.UserRole) or item.text()))
            if not data:
                continue
            data = dict(data)
            image_bytes = data.pop('image', b'')
            if image_bytes:
                from PySide6.QtCore import QByteArray, QBuffer, QIODevice
                from PySide6.QtGui import QImageReader
                buffer = QBuffer()
                buffer.setData(QByteArray(image_bytes))
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader = QImageReader(buffer)
                size = reader.size()
                if 0 < size.width() <= 2048 and 0 < size.height() <= 2048:
                    reader.setScaledSize(QSize(48, 48))
                    image = reader.read()
                    if not image.isNull():
                        item.setIcon(QIcon(QPixmap.fromImage(image)))
            item.setData(CARD_ROLE, data)
            item.setToolTip('\n'.join(filter(None, [data['name'], item.text(), data.get('description', ''), data.get('warning', '')])))


def load_cards(widget, directory, loader='', minecraft=''):
    if not hasattr(widget, '_card_loader'):
        widget._card_loader = CardLoader(widget)
    widget._card_loader.refresh(directory, loader, minecraft)
