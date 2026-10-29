import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from launcher_app.resources.pack_downloads import new_download_directory


def test_each_download_gets_permanent_separate_directory(tmp_path):
    first = Path(new_download_directory(str(tmp_path)))
    second = Path(new_download_directory(str(tmp_path)))
    assert first != second
    assert first.parent == second.parent == tmp_path / 'downloads' / 'modpacks'


@pytest.mark.parametrize('failed', [False, True])
@pytest.mark.parametrize('entry', ['ai', 'gui'])
def test_original_archive_survives_import_success_and_failure(tmp_path, failed, entry):
    originals = []
    def download(ref, directory, **kwargs):
        path = Path(directory, 'friends.mrpack')
        path.write_bytes(b'original archive bytes')
        originals.append(path)
        return str(path)
    def install(path, *args, **kwargs):
        assert Path(path).read_bytes() == b'original archive bytes'
        if failed:
            raise ValueError('installation failed')
        return 'installed'
    with patch('launcher_app.resources.modrinth.download_modpack', side_effect=download), \
         patch('launcher_app.resources.modrinth.get_project', return_value={'project_type': 'modpack', 'title': 'Friends'}), \
         patch('launcher_app.resources.modrinth.get_modpack_file', return_value={'url': 'https://example.invalid/file'}), \
         patch('launcher_app.resources.modpack.import_modpack', side_effect=install):
        if entry == 'ai':
            from launcher_app.ai.agent_tools import install_modpack
            message = install_modpack('friends', game_dir=str(tmp_path))
        else:
            # Exercise the actual GUI worker without starting a real window/network.
            tree = ast.parse(Path('main.py').read_text(encoding='utf-8-sig'))
            method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                          and n.name == '_resource_download_modpack')
            namespace = {'os': __import__('os'), 'paths': SimpleNamespace(GAME_DIR=str(tmp_path))}
            exec(compile(ast.Module(body=[method], type_ignores=[]), 'main.py', 'exec'), namespace)
            messages = []
            owner = SimpleNamespace(_run_download=lambda worker: worker(messages.append, lambda *args: None))
            namespace[method.name](owner, {'slug': 'friends'}, None)
            message = messages[-1]
    assert originals[0].read_bytes() == b'original archive bytes'
    assert str(originals[0]) in message
