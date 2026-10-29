import json
from unittest.mock import Mock, patch

import launcher_app.instances.loaders as loaders
from launcher_app.instances.instances import _detect_loader
from launcher_app.resources.modpack import _cf_loader, _ftb_loader, _install_loader_from_deps


def test_quilt_versions_stable_first_and_numeric_order():
    response=Mock()
    response.json.return_value=[{'loader':{'version':v}} for v in ['0.9.0','0.28.0-beta.2','0.27.1','0.27.0','0.28.0-beta.10']]
    with patch('launcher_app.instances.loaders.requests.get',return_value=response):
        assert loaders.list_quilt_loaders('1.20.1') == ['0.27.1','0.27.0','0.9.0','0.28.0-beta.10','0.28.0-beta.2']


def test_quilt_profile_uses_declared_repository():
    response=Mock()
    response.json.return_value={'id':'quilt-loader-0.27.1-1.20.1','inheritsFrom':'1.20.1',
        'mainClass':'org.quiltmc.loader.impl.launch.knot.KnotClient',
        'libraries':[{'name':'org.quiltmc:quilt-loader:0.27.1','url':'https://maven.quiltmc.org/repository/release/'}]}
    with patch('launcher_app.instances.loaders.requests.get',return_value=response):
        profile=loaders._quilt_profile('1.20.1','0.27.1')
    artifact=profile['libraries'][0]['downloads']['artifact']
    assert artifact['url'] == 'https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-loader/0.27.1/quilt-loader-0.27.1.jar'


def test_quilt_is_not_misidentified_as_fabric():
    assert _detect_loader('Renamed', {'libraries':[{'name':'net.fabricmc:tiny-mappings-parser:1'},
        {'name':'org.quiltmc:quilt-loader:0.27.1'}]}) == 'quilt'


def test_modpack_formats_preserve_quilt_loader():
    with patch('launcher_app.resources.modpack.install_loader',return_value='quilt-instance') as install:
        assert _install_loader_from_deps({'quilt-loader':'0.27.1'},'1.20.1','game') == 'quilt-instance'
    assert install.call_args.args[0] == 'quilt'
    assert install.call_args.kwargs['loader_version'] == '0.27.1'
    assert _cf_loader({'minecraft':{'modLoaders':[{'id':'quilt-0.27.1','primary':True}]}}) == ('quilt','0.27.1')
    assert _ftb_loader({'loaders':['quilt-0.27.1']}) == ('quilt','0.27.1')


def test_install_quilt_saves_real_profile_and_resolves_dependencies(tmp_path):
    base=tmp_path/'versions'/'_versions'/'1.20.1'
    base.mkdir(parents=True)
    (base/'1.20.1.json').write_text(json.dumps({'id':'1.20.1','libraries':[]}),encoding='utf-8')
    (base/'1.20.1.jar').write_bytes(b'base')
    profile={'id':'quilt-loader-0.27.1-1.20.1','inheritsFrom':'1.20.1',
        'mainClass':'org.quiltmc.loader.impl.launch.knot.KnotClient','libraries':[]}
    with patch('launcher_app.instances.loaders._quilt_profile',return_value=profile), \
         patch('launcher_app.instances.loaders.install_version_files',return_value=(0,[])) as files:
        identifier=loaders.install_loader('quilt','1.20.1',str(tmp_path),loader_version='0.27.1')
    result=json.loads((tmp_path/'versions'/identifier/(identifier+'.json')).read_text(encoding='utf-8'))
    assert result['mainClass'].startswith('org.quiltmc.')
    assert files.call_args.args[0]['mainClass'] == result['mainClass']
    assert (tmp_path/'versions'/identifier/(identifier+'.jar')).read_bytes() == b'base'


def test_agent_install_accepts_quilt_without_substituting_fabric(tmp_path):
    from launcher_app.ai.agent_tools import install_instance
    with patch('launcher_app.ai.agent_tools.ensure_base'), \
         patch('launcher_app.ai.agent_tools.install_loader',return_value='quilt-instance') as install:
        result=install_instance('1.20.1',loader='quilt',loader_version='0.27.1',
                                game_dir=str(tmp_path),optimize=False,shader=False)
    assert result == '实例就绪:quilt-instance'
    assert install.call_args.args[0] == 'quilt'
    assert install.call_args.kwargs['loader_version'] == '0.27.1'
