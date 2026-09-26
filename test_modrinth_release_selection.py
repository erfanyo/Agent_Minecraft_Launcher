import unittest
from unittest.mock import patch

import modrinth


class _Response:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return self._rows


def _version(number, kind):
    return {
        "version_number": number,
        "version_type": kind,
        "files": [{
            "primary": True,
            "filename": number + ".jar",
            "url": "https://example.invalid/" + number,
            "hashes": {"sha1": number},
        }],
        "dependencies": [],
    }


class ReleaseSelectionTests(unittest.TestCase):
    def find(self, rows, requested=None):
        with patch.object(modrinth.requests, "get", return_value=_Response(rows)):
            return modrinth._find_version("example", "1.21.1", "neoforge", requested)

    def test_automatic_selection_accepts_newer_beta(self):
        found = self.find([_version("2.0-beta.1", "beta"), _version("1.9", "release")])
        self.assertEqual(found["version_number"], "2.0-beta.1")

    def test_explicit_prerelease_is_still_selectable(self):
        found = self.find([_version("2.0-beta.1", "beta"), _version("1.9", "release")],
                          "2.0-beta.1")
        self.assertEqual(found["version_number"], "2.0-beta.1")

    def test_prerelease_only_project_uses_newest_available(self):
        found = self.find([_version("2.0-beta.2", "beta"), _version("2.0-beta.1", "beta")])
        self.assertEqual(found["version_number"], "2.0-beta.2")


if __name__ == "__main__":
    unittest.main()
