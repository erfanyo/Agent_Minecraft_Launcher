import hashlib
from unittest.mock import patch

import pytest

import launcher_app.resources.curseforge as curseforge
from launcher_app.resources.resource_catalog import search_page


@pytest.mark.parametrize('kind,class_id', [('mod', 6), ('modpack', 4471), ('shader', 6552),
                                         ('datapack', 6945), ('resourcepack', 12)])
def test_cf_search_routes_all_resource_types(kind, class_id):
    with patch('launcher_app.resources.curseforge._get', return_value=[]) as get:
        assert curseforge.search_mods('test', project_type=kind) == []
    assert get.call_args.args[1]['classId'] == class_id


def test_all_sources_keep_independent_offsets_when_one_ends():
    mr_pages = [[{'slug': str(i)} for i in range(30)], [{'slug': 'last'}]]
    with patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.search_mods', return_value=[{'source': 'curseforge', 'slug': 'cf'}]) as cf, \
         patch('launcher_app.resources.modrinth.search_mods_cn', side_effect=mr_pages) as mr:
        first = search_page('all', 'shader', '', 'relevance')
        assert len(first['hits']) == 31 and not first['no_more']
        second = search_page('all', 'shader', '', 'relevance', offsets=first['offsets'], exhausted=first['exhausted'])
    assert cf.call_count == 1
    assert mr.call_args.kwargs['offset'] == 30
    assert second['no_more']
    assert second['offsets'] == {'modrinth': 31, 'curseforge': 1}


def test_one_source_failure_keeps_other_results():
    with patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.search_mods', side_effect=RuntimeError('offline')), \
         patch('launcher_app.resources.modrinth.search_mods_cn', return_value=[{'slug': 'working'}]):
        result = search_page('all', 'datapack', '', 'downloads')
    assert result['hits'][0]['slug'] == 'working'
    assert result['hits'][0]['source'] == 'modrinth'
    assert 'curseforge' in result['errors']


def test_all_sources_without_key_still_searches_modrinth():
    with patch('launcher_app.resources.curseforge.configured', return_value=False), \
         patch('launcher_app.resources.curseforge.search_mods') as cf, \
         patch('launcher_app.resources.modrinth.search_mods_cn', return_value=[{'slug': 'working'}]):
        result = search_page('all', 'modpack', '', 'downloads')
    cf.assert_not_called()
    assert len(result['hits']) == 1
    assert 'API Key' in result['errors']['curseforge']


def test_cf_loader_and_game_version_filters_exclude_server_packs():
    files = [
        {'id': 1, 'fileName': 'wrong.jar', 'gameVersions': ['1.20.1', 'Fabric']},
        {'id': 2, 'fileName': 'right.jar', 'gameVersions': ['1.20.1', 'Forge']},
        {'id': 3, 'fileName': 'server.zip', 'gameVersions': ['1.20.1', 'Forge'], 'isServerPack': True},
    ]
    with patch('launcher_app.resources.curseforge._get', return_value=files) as get:
        result = curseforge.list_mod_files(10, '1.20.1', loader='forge')
    assert [file['file_id'] for file in result] == [2]
    assert get.call_args.args[1]['modLoaderType'] == 1
    assert get.call_args.args[1]['gameVersion'] == '1.20.1'


@pytest.mark.parametrize('class_id', [4471, 6552, 6945, 12])
def test_cf_download_resources_to_requested_target(tmp_path, class_id):
    file = {'id': 20, 'modId': 10, 'fileName': 'resource.zip',
            'downloadUrl': 'https://edge.forgecdn.net/resource.zip',
            'hashes': [{'algo': 1, 'value': hashlib.sha1(b'ok').hexdigest()}]}
    with patch('launcher_app.resources.curseforge._get', side_effect=[file, {'id': 10, 'classId': class_id}]), \
         patch('launcher_app.resources.curseforge._headers', return_value={}), patch('launcher_app.resources.curseforge.download_file') as download:
        assert curseforge.download_mod(10, 20, str(tmp_path)) == 'resource.zip'
    assert download.call_args.args[1] == str(tmp_path / 'resource.zip')


def test_project_search_filters_reach_both_platforms():
    with patch('launcher_app.resources.curseforge.configured', return_value=True), \
         patch('launcher_app.resources.curseforge.search_mods', return_value=[]) as cf, \
         patch('launcher_app.resources.modrinth.search_mods_cn', return_value=[]) as mr:
        search_page('all', 'mod', '', 'downloads', game_version='1.20.1', loader='fabric')
    assert cf.call_args.args[1] == '1.20.1'
    assert cf.call_args.kwargs['loader'] == 'fabric'
    assert mr.call_args.args[1:3] == ('1.20.1', 'fabric')
