from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QWidget, QMessageBox
from launcher_app.ui.command_setup_controller import CommandSetupController
from launcher_app.ui.instance_actions_controller import InstanceActionsController


def test_install_after_bridge_check_keeps_original_directory(qtbot,tmp_path):
    parent=QWidget();qtbot.addWidget(parent)
    current=[str(tmp_path/'old')];jobs=[]
    controller=CommandSetupController(parent=parent,game_dir_for=lambda _:current[0],submit=jobs.append,show_status=lambda _:None,clear_status=lambda:None)
    instance=controller._capture({'id':'one','loader':'fabric','base':'1.20.1'})
    current[0]=str(tmp_path/'new')
    with patch('launcher_app.ui.command_setup_controller.action_question',return_value=QMessageBox.StandardButton.Yes):
        controller._on_bridge_status_ready(instance,{'status':'not_installed','info':{'version':'1'}})
    assert jobs[0].__self__.game_dir==str(tmp_path/'old')


def test_vanilla_rcon_notice_uses_widget_parent(qtbot,tmp_path):
    parent=QWidget();qtbot.addWidget(parent)
    controller=CommandSetupController(parent=parent,game_dir_for=lambda _:str(tmp_path),submit=lambda _:None,show_status=lambda _:None,clear_status=lambda:None)
    with patch('launcher_app.instances.game_command.read_rcon_config',return_value=None),patch('launcher_app.instances.game_command.has_lan_server_properties',return_value=False),patch('launcher_app.ui.command_setup_controller.inline_notice') as notice:
        controller._one_click_rcon_for({'id':'one','loader':None,'base':'1.20.1'})
    assert notice.call_args.args[0] is parent


def actions(parent,service,*,busy=False,settings=None,refresh=None,select=None):
    return InstanceActionsController(parent=parent,service_factory=lambda:service,busy_any=lambda:busy,busy_instance=lambda _:busy,settings=lambda:settings or {},save_last_played=lambda _:None,refresh=refresh or (lambda:None),select=select or (lambda _:None),reload_versions=lambda:None,show_status=lambda _:None,log_feedback=lambda _:None)


def test_clear_busy_never_deletes(qtbot):
    from unittest.mock import Mock
    parent=QWidget();qtbot.addWidget(parent);service=Mock()
    with patch('launcher_app.ui.instance_actions_controller.inline_notice'),patch('launcher_app.ui.instance_actions_controller.action_question') as question:
        actions(parent,service,busy=True).clear()
    service.clear_all.assert_not_called();question.assert_not_called()


def test_rename_updates_last_played_and_selection(qtbot):
    parent=QWidget();qtbot.addWidget(parent);settings={'last_played_instance':'old'};selected=[]
    service=SimpleNamespace(rename=lambda old,name:name.strip())
    with patch('launcher_app.ui.instance_actions_controller.QInputDialog.getText',return_value=(' new ',True)):
        actions(parent,service,settings=settings,select=selected.append).rename({'id':'old'})
    assert settings['last_played_instance']=='new'
    assert selected==['new']


def test_delete_failure_is_reported_without_success_or_refresh(qtbot):
    from unittest.mock import Mock
    parent=QWidget();qtbot.addWidget(parent)
    service=Mock();service.delete.side_effect=PermissionError('locked')
    refresh=Mock();controller=actions(parent,service,refresh=refresh)
    controller.show_status=Mock()
    with patch('launcher_app.ui.instance_actions_controller.action_question',return_value=QMessageBox.StandardButton.Yes),patch('launcher_app.ui.instance_actions_controller.task_warning') as warning:
        controller.delete({'id':'one'})
    warning.assert_called_once()
    controller.show_status.assert_not_called();refresh.assert_not_called()


def test_clear_partial_failure_never_claims_all_removed(qtbot):
    from unittest.mock import Mock
    from launcher_app.instances.instance_actions import ClearInstancesResult
    parent=QWidget();qtbot.addWidget(parent)
    service=Mock();service.clear_all.return_value=ClearInstancesResult(('good',),(('locked','in use'),))
    controller=actions(parent,service);controller.show_status=Mock()
    with patch('launcher_app.ui.instance_actions_controller.action_question',return_value=QMessageBox.StandardButton.Yes),patch('launcher_app.ui.instance_actions_controller.task_warning') as warning:
        controller.clear()
    assert 'locked' in warning.call_args.args[2]
    controller.show_status.assert_not_called()


def test_cancel_rename_does_not_change_files(qtbot):
    from unittest.mock import Mock
    parent=QWidget();qtbot.addWidget(parent);service=Mock()
    with patch('launcher_app.ui.instance_actions_controller.QInputDialog.getText',return_value=('new',False)):
        actions(parent,service).rename({'id':'one'})
    service.rename.assert_not_called()
