"""Verify preflight and user choices without constructing the launcher window."""
from unittest.mock import Mock, patch
import pytest
from PySide6.QtWidgets import QWidget
from launcher_app.ui.pack_import_controller import PackImportController

pytestmark=pytest.mark.ui


def build(qtbot, root='games', smart=False):
    parent=QWidget(); qtbot.addWidget(parent)
    ports={name:Mock() for name in ('smart_import','choose_archive','check_archive','import_server',
                                   'import_directory','submit','show_status')}
    controller=PackImportController(parent=parent,smart_enabled=lambda:smart,game_root=lambda:root,**ports)
    return controller,ports


def test_preflight_must_finish_before_job_submission(qtbot):
    controller,ports=build(qtbot)
    controller.import_archive('outer.zip')
    ports['submit'].assert_not_called()
    with patch('launcher_app.ui.pack_import_controller.detect_modpack_format',return_value='modrinth'), \
         patch('launcher_app.ui.pack_import_controller.suggested_instance_id',return_value='new'):
        ports['check_archive'].call_args.args[1]('checked.mrpack')
    job=ports['submit'].call_args.args[0].__self__
    assert job.path=='checked.mrpack' and job.game_root=='games'


def test_smart_import_keeps_existing_preflight_flag(qtbot):
    controller,ports=build(qtbot,smart=True)
    controller.import_archive('pack.zip',safety_checked=True,classic=False)
    ports['smart_import'].assert_called_once_with('pack.zip',safety_checked=True)
    ports['submit'].assert_not_called()


def test_flat_version_prompt_cancel_does_not_install(qtbot):
    controller,ports=build(qtbot)
    with patch('launcher_app.ui.pack_import_controller.detect_modpack_format',return_value='flat'), \
         patch('launcher_app.ui.pack_import_controller.QInputDialog.getText',return_value=('',False)):
        controller.import_archive('pack.zip',safety_checked=True)
    ports['submit'].assert_not_called()


def test_name_conflict_cancel_does_not_overwrite(qtbot,tmp_path):
    (tmp_path/'versions'/'friends').mkdir(parents=True)
    controller,ports=build(qtbot,str(tmp_path))
    with patch('launcher_app.ui.pack_import_controller.detect_modpack_format',return_value='modrinth'), \
         patch('launcher_app.ui.pack_import_controller.suggested_instance_id',return_value='friends'), \
         patch('launcher_app.ui.pack_import_controller.QInputDialog.getText',return_value=('',False)):
        controller.import_archive('pack.zip',safety_checked=True)
    ports['submit'].assert_not_called()
