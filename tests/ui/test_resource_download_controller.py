"""Dependency decisions are frontend concerns; no download runs on cancellation."""
from unittest.mock import Mock,patch
import pytest
from PySide6.QtWidgets import QWidget
from launcher_app.ui.resource_download_controller import ResourceDownloadController
from launcher_app.resources.download_jobs import DependencyReview

pytestmark=pytest.mark.ui


def test_dependency_cancel_does_not_submit_job(qtbot):
    parent=QWidget();qtbot.addWidget(parent)
    submit=Mock()
    controller=ResourceDownloadController(parent=parent,submit=submit,show_status=Mock(),game_root=lambda:'games')
    with patch('launcher_app.ui.resource_download_controller.ResourceDownloadJob') as factory, \
         patch('launcher_app.ui.resource_download_controller.task_choice',return_value=None):
        factory.return_value.dependency_review.return_value=DependencyReview(missing=({'title':'Dependency'},))
        controller.download({'slug':'one'},None,{},'target','mods')
    submit.assert_not_called()


def test_missing_cf_version_is_reported_before_submission(qtbot):
    parent=QWidget();qtbot.addWidget(parent)
    submit,status=Mock(),Mock()
    controller=ResourceDownloadController(parent=parent,submit=submit,show_status=status,game_root=lambda:'games')
    controller.download({'source':'curseforge'},None,None,'target','mods')
    submit.assert_not_called()
    assert 'CurseForge' in status.call_args.args[0]


def test_skip_dependencies_is_an_explicit_job_input(qtbot):
    parent=QWidget();qtbot.addWidget(parent)
    workers=[]
    controller=ResourceDownloadController(parent=parent,submit=workers.append,show_status=Mock(),game_root=lambda:'games')
    with patch('launcher_app.ui.resource_download_controller.ResourceDownloadJob') as factory, \
         patch('launcher_app.ui.resource_download_controller.task_choice',return_value='skip'):
        job=factory.return_value
        job.dependency_review.return_value=DependencyReview(missing=({'title':'Dependency'},))
        controller.download({'slug':'one'},None,{},'target','mods')
        workers[0](Mock(),Mock())
        assert job.run.call_args.kwargs=={'dependencies':(), 'skipped_dependencies':True}
