"""Captured downloads can run with no main window, network or real account."""
from pathlib import Path
from unittest.mock import patch
import pytest
from launcher_app.core.task_context import TaskCancelled
from launcher_app.resources.download_jobs import ArchiveImportJob, PackDownloadJob, ResourceDownloadJob, resource_preferences


@pytest.mark.parametrize('kind,version,loader', [
    ('mods','1.20.1','forge'), ('shaderpacks',None,None),
    ('resourcepacks','1.20.1',None), ('datapacks','1.20.1',None)])
def test_target_preferences_respect_version_insensitive_resources(kind,version,loader):
    pref=resource_preferences({'base':'1.20.1','loader':'forge'},kind)
    assert (pref.game_version,pref.loader)==(version,loader)


def test_resource_selection_is_captured_and_no_file_is_failure():
    hit={'slug':'one'}; instance={'base':'1.20.1','loader':'forge'}; version={'id':'selected'}
    job=ResourceDownloadJob(hit,version,instance,'target','mods')
    hit['slug']='other'; instance['base']='1.21.1'; version['id']='other'
    with patch('launcher_app.resources.modrinth.download_mod',return_value=None) as download:
        with pytest.raises(RuntimeError,match='1.20.1'):
            job.run(lambda _:None,lambda *a:None)
    assert download.call_args.args[:4]==('one','1.20.1','forge','target')
    assert download.call_args.kwargs['version_number']=={'id':'selected'}


def test_archive_import_targets_captured_root():
    job=ArchiveImportJob('original.zip','root-one',mc_version='1.12.2',loader='forge',instance_id='friends')
    with patch('launcher_app.resources.modpack.import_modpack',return_value='friends') as install:
        assert job.run(lambda _:None,lambda *a:None)=='friends'
    assert install.call_args.args==('original.zip','root-one')
    assert install.call_args.kwargs['instance_id']=='friends'


@pytest.mark.parametrize('provider',['modrinth','curseforge'])
def test_cancel_is_not_converted_to_download_error(tmp_path,provider):
    hit={'slug':'friends','source':provider,'curseforge_id':42}
    version={'file_id':7}
    function='launcher_app.resources.curseforge.download_mod' if provider=='curseforge' else 'launcher_app.resources.modrinth.download_modpack'
    with patch(function,side_effect=TaskCancelled()):
        with pytest.raises(TaskCancelled):
            PackDownloadJob(hit,version,str(tmp_path)).run(lambda _:None,lambda *a:None)


def test_dependency_cancel_is_not_swallowed():
    job=ResourceDownloadJob({'slug':'one'},None,{'base':'1.20.1','loader':'forge'},'target','mods')
    with patch('launcher_app.resources.modrinth.installed_mod_identifiers',return_value=set()), \
         patch('launcher_app.resources.modrinth.download_mod',side_effect=TaskCancelled()):
        with pytest.raises(TaskCancelled):
            job.run(lambda _:None,lambda *a:None,dependencies=[{'slug':'dependency','title':'Dependency'}])
