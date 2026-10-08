import unittest
from unittest.mock import Mock, patch

from loaders import list_neoforge_versions


def _json_response(versions):
    response = Mock()
    response.json.return_value = {"isSnapshot": False, "versions": versions}
    return response


class LoaderVersionTests(unittest.TestCase):
    def test_neoforge_1211_uses_json_api_and_filters_211(self):
        """版本列表优先走官方 JSON API:Reposilite 的 maven-metadata.xml 常年 404。"""
        response = _json_response(["21.1.248", "21.1.250", "21.4.10-beta"])
        with patch("loaders.requests.get", return_value=response) as get:
            versions = list_neoforge_versions("1.21.1")

        get.assert_called_once()
        self.assertIn("/api/maven/versions/releases/net/neoforged/neoforge",
                      get.call_args.args[0])
        self.assertEqual(versions, ["21.1.250", "21.1.248"])

    def test_neoforge_1201_uses_legacy_forge_artifact(self):
        """1.20.1 的 NeoForge 沿用 net.neoforged:forge 坐标,版本带 1.20.1- 前缀。"""
        response = _json_response(["1.20.1-47.1.105", "1.20.1-47.1.106", "21.1.250"])
        with patch("loaders.requests.get", return_value=response) as get:
            versions = list_neoforge_versions("1.20.1")

        self.assertIn("/net/neoforged/forge", get.call_args.args[0])
        self.assertEqual(versions, ["1.20.1-47.1.106", "1.20.1-47.1.105"])

    def test_neoforge_xml_fallback_when_api_fails(self):
        """API 不可用时,回退解析 maven-metadata.xml(保留旧行为作为兜底)。"""
        api_fail = Mock()
        api_fail.raise_for_status.side_effect = RuntimeError("api down")
        xml_ok = Mock()
        xml_ok.text = (
            "<metadata><versioning><versions>"
            "<version>21.1.248</version><version>21.1.250</version>"
            "</versions></versioning></metadata>"
        )
        with patch("loaders.requests.get", side_effect=[api_fail, xml_ok]) as get:
            versions = list_neoforge_versions("1.21.1")

        self.assertEqual(get.call_count, 2)
        self.assertEqual(versions, ["21.1.250", "21.1.248"])


if __name__ == "__main__":
    unittest.main()
