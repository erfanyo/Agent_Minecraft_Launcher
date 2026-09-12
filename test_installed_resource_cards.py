import json
import os
import tempfile
import unittest
import zipfile

from installed_resource_cards import (read_card, warning, incompatible_version,
                                      loaded_mod_evidence)


class CardTests(unittest.TestCase):
    def test_render(self):
        from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem
        from PySide6.QtCore import Qt
        from installed_resource_cards import CardLoader
        app = QApplication.instance() or QApplication([])
        widget = QListWidget()
        item = QListWidgetItem('example.jar')
        item.setData(Qt.ItemDataRole.UserRole, 'example.jar')
        widget.addItem(item)
        loader = CardLoader(widget)
        loader.apply(0, [('example.jar', {'name': '测试卡片', 'description': '说明', 'warning': '不兼容'})])
        widget.resize(480, 150)
        widget.show()
        app.processEvents()
        self.assertFalse(widget.grab().isNull())
        widget.close()

    def test_versions(self):
        self.assertTrue(incompatible_version('1.19.2', '[1.20,1.21)'))
        self.assertFalse(incompatible_version('1.20.1', '[1.20,1.21)'))
        self.assertFalse(incompatible_version('1.20.1', '>=1.20'))
        self.assertTrue(incompatible_version('1.21', '[1.20,1.21)'))
        self.assertFalse(warning({'formats': ['neoforge'], 'mc': '[1.21,1.21.1)'},
                                 'neoforge', '1.21.1', loaded_successfully=True))

    def test_loader(self):
        self.assertTrue(warning({'formats': ['fabric']}, 'forge', '1.20.1'))
        self.assertFalse(warning({'formats': ['fabric', 'forge']}, 'forge', '1.20.1'))
        self.assertFalse(warning({'formats': []}, 'forge', '1.20.1'))

    def test_local_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'test.jar')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps({'id': 'test', 'name': '测试 Mod', 'icon': 'icon.png'}))
                archive.writestr('icon.png', b'example')
            data = read_card(path, 0, 0)
            self.assertEqual(data['name'], '测试 Mod')
            self.assertEqual(data['image'], b'example')
            self.assertEqual(data['formats'], ['fabric'])
            self.assertEqual(data['id'], 'test')

    def test_latest_log_provides_loaded_mod_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            mods = os.path.join(folder, 'mods')
            logs = os.path.join(folder, 'logs')
            os.makedirs(mods)
            os.makedirs(logs)
            with open(os.path.join(logs, 'latest.log'), 'w', encoding='utf-8') as file:
                file.write('Reloading ResourceManager: vanilla, mod/iris, mod/jei\n')
            ids, timestamp = loaded_mod_evidence(mods)
        self.assertEqual(ids, {'iris', 'jei'})
        self.assertGreater(timestamp, 0)


if __name__ == '__main__':
    unittest.main()
