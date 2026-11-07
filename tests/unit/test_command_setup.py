from unittest.mock import patch
import pytest
from launcher_app.instances.command_setup import CommandSetupRequest
from launcher_app.core.task_context import TaskCancelled


def test_bridge_check_uses_captured_instance_and_directory(tmp_path):
    inst={'id':'one','loader':'fabric','base':'1.20.1'}
    request=CommandSetupRequest.capture(inst,tmp_path)
    inst.update(base='1.21',loader='forge')
    with patch('launcher_app.core.bridge_mod_dist.check_bridge_mod',return_value='not_installed') as check, patch('launcher_app.core.bridge_mod_dist.bridge_mod_info',return_value={'version':'1'}) as info:
        assert request.check_bridge()=={'status':'not_installed','info':{'version':'1'}}
    check.assert_called_once_with(str(tmp_path),'fabric','1.20.1')
    info.assert_called_once_with('fabric','1.20.1')


def test_missing_lan_mod_does_not_configure_rcon(tmp_path):
    request=CommandSetupRequest.capture({'id':'one','loader':'fabric','base':'1.20.1'},tmp_path)
    with patch('launcher_app.resources.modrinth.download_mod',return_value=None), patch('launcher_app.instances.game_command.ensure_rcon_config') as config:
        assert request.install_lan_properties(lambda _:None,lambda *a:None) is False
    config.assert_not_called()


@pytest.mark.parametrize('method,target',[('install_bridge','launcher_app.core.bridge_mod_dist.download_bridge_mod'),('install_lan_properties','launcher_app.resources.modrinth.download_mod')])
def test_cancellation_is_not_wrapped_as_failure(tmp_path,method,target):
    request=CommandSetupRequest.capture({'id':'one','loader':'fabric','base':'1.20.1'},tmp_path)
    with patch(target,side_effect=TaskCancelled),pytest.raises(TaskCancelled):
        getattr(request,method)(lambda _:None,lambda *a:None)
