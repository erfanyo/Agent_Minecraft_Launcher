import marshal
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from tools.bundle_credentials import credential_code, inject_credentials, MODULE
from launcher_app.resources import curseforge
from launcher_app.core.log_privacy import redact_text


def test_obfuscation_roundtrip_and_randomization():
    key = 'test-approved-key-12345'
    first, second = credential_code(key), credential_code(key)
    namespace = {}
    exec(first, namespace)
    assert namespace['curseforge_key']() == key
    assert key.encode() not in marshal.dumps(first)
    assert marshal.dumps(first) != marshal.dumps(second)


def test_custom_precedes_bundle_and_source_has_no_bundle():
    with patch.object(curseforge, 'load_settings', return_value={'curseforge_api_key': 'custom'}):
        assert curseforge.api_key() == 'custom'
    with patch.object(curseforge, 'load_settings', return_value={}):
        with patch('sys.frozen', True, create=True), patch(
                'launcher_app.runtime.bundled_credentials.curseforge_key', return_value='bundle'):
            assert curseforge.api_key() == 'bundle'
        assert curseforge.api_key() == ''


def test_bundle_redacted_without_settings():
    with patch('sys.frozen', True, create=True), patch(
            'launcher_app.runtime.bundled_credentials.curseforge_key', return_value='test-secret-bundle'):
        assert 'test-secret-bundle' not in redact_text('failure test-secret-bundle')


def test_pyinstaller_code_cache_injection(tmp_path, monkeypatch):
    CONF = pytest.importorskip('PyInstaller.config').CONF
    monkeypatch.setenv('AMCL_RELEASE_CURSEFORGE_KEY', 'test-build-key')
    analysis = SimpleNamespace(pure=[(MODULE, 'stub.py', 'PYMODULE')])
    cache = {}
    monkeypatch.setitem(CONF, 'code_cache', {id(analysis.pure): cache})
    inject_credentials(analysis, tmp_path)
    namespace = {}
    exec(cache[MODULE], namespace)
    assert namespace['curseforge_key']() == 'test-build-key'
