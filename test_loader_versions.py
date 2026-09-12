import unittest
from unittest.mock import Mock, patch

from loaders import list_neoforge_versions


class LoaderVersionTests(unittest.TestCase):
    def test_neoforge_1211_matches_211_releases(self):
        response = Mock()
        response.text = (
            '<metadata><versioning><versions>'
            '<version>21.1.248</version><version>21.1.250</version>'
            '<version>21.4.10-beta</version>'
            '</versions></versioning></metadata>'
        )
        with patch('loaders.requests.get', return_value=response):
            versions = list_neoforge_versions('1.21.1')

        response.raise_for_status.assert_called_once_with()
        self.assertEqual(versions, ['21.1.250', '21.1.248'])


if __name__ == '__main__':
    unittest.main()
