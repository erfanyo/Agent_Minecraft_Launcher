import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server_eula import accept_minecraft_eula, fetch_minecraft_eula
from server_launch import eula_accepted


class ServerEulaTests(unittest.TestCase):
    def test_dialog_unlocks_only_at_the_bottom(self):
        from PySide6.QtWidgets import QApplication
        from server_center import MinecraftEulaDialog
        app = QApplication.instance() or QApplication([])
        dialog = MinecraftEulaDialog({
            'text': '\n'.join(f'EULA line {i}' for i in range(500)),
            'url': 'https://www.minecraft.net/eula',
        })
        dialog.show()
        app.processEvents()
        bar = dialog.text.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertFalse(dialog.accept_button.isEnabled())
        bar.setValue(bar.maximum())
        app.processEvents()
        self.assertTrue(dialog.accept_button.isEnabled())
        dialog.close()

    def test_fetches_only_official_complete_eula(self):
        body = ('<html><main><h1>Minecraft End(er)-User License Agreement</h1>'
                '<p>' + ('Terms and conditions. ' * 180) + '</p>'
                '<p>Mojang AB</p></main><script>ignored</script></html>')
        response = Mock(url='https://www.minecraft.net/en-us/eula',
                        content=body.encode(), text=body)
        response.raise_for_status.return_value = None
        with patch('server_eula.requests.get', return_value=response) as get:
            payload = fetch_minecraft_eula()
        self.assertIn('Minecraft End(er)-User License Agreement', payload['text'])
        self.assertNotIn('ignored', payload['text'])
        get.assert_called_once()

    def test_rejects_redirect_away_from_official_site(self):
        response = Mock(url='https://example.com/eula', content=b'', text='')
        response.raise_for_status.return_value = None
        with patch('server_eula.requests.get', return_value=response), \
                self.assertRaisesRegex(ValueError, '非 Minecraft 官方网站'):
            fetch_minecraft_eula()

    def test_acceptance_is_explicit_atomic_and_preserves_comments(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'eula.txt')
            path.write_text('# generated\neula=false\ncustom=value\n', encoding='utf-8')
            accept_minecraft_eula(root)
            text = path.read_text(encoding='utf-8')
            self.assertIn('# generated', text)
            self.assertIn('custom=value', text)
            self.assertNotIn('eula=false', text)
            self.assertEqual(text.count('eula=true'), 1)
            self.assertTrue(eula_accepted(root))
            self.assertFalse(list(Path(root).glob('.amcl-eula-*.pending')))


if __name__ == '__main__':
    unittest.main()
