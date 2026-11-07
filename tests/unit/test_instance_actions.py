from pathlib import Path
from unittest.mock import patch
import pytest
from launcher_app.instances.instance_actions import InstanceActions


def test_delete_preserves_shared_files_and_other_instances(tmp_path):
    for folder in ('versions/one', 'versions/two', 'saves/world', 'libraries'):
        p=tmp_path/folder;p.mkdir(parents=True);(p/'keep').write_text('data')
    InstanceActions(tmp_path).delete('one')
    assert not (tmp_path/'versions/one').exists()
    assert all((tmp_path/p/'keep').exists() for p in ('versions/two','saves/world','libraries'))


@pytest.mark.parametrize('name', ['../outside', '..', 'one/two', 'one\\two'])
def test_delete_rejects_path_escape(tmp_path, name):
    with pytest.raises(ValueError):
        InstanceActions(tmp_path).delete(name)


def test_delete_rejects_directory_link(tmp_path):
    with patch('os.path.islink', return_value=True), pytest.raises(ValueError):
        InstanceActions(tmp_path).delete('one')


def test_clear_reports_partial_failure(tmp_path):
    for name in ('good','locked'):
        (tmp_path/'versions'/name).mkdir(parents=True)
    import shutil
    original=shutil.rmtree
    def remove(path):
        if Path(path).name=='locked':
            raise PermissionError('in use')
        original(path)
    with patch('launcher_app.instances.instance_actions.shutil.rmtree',side_effect=remove):
        result=InstanceActions(tmp_path).clear_all()
    assert result.removed==('good',)
    assert result.failures==( ('locked','in use'), )
    assert (tmp_path/'versions/locked').is_dir()


def test_clear_rejects_versions_link_even_to_another_folder_inside_root(tmp_path):
    versions=tmp_path/'versions'
    with patch('os.path.islink',side_effect=lambda path: Path(path)==versions),pytest.raises(ValueError):
        InstanceActions(tmp_path).clear_all()
