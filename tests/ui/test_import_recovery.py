import pytest
from launcher_app.ui.import_recovery import ImportRecoveryController
from launcher_app.resources.import_recovery import remember, preserve_failed_source, pending
from launcher_app.instances.instance_metadata import atomic_json
import hashlib

pytestmark = pytest.mark.ui


def test_closed_tab_and_unrelated_success_cannot_clear_x(hub, tmp_path):
    source = tmp_path/'pack.zip'; source.write_bytes(b'pack')
    instance = tmp_path/'versions'/'Pack'; instance.mkdir(parents=True)
    atomic_json(str(instance.parent/'_imports'/'Pack.json'), {'archive': 'hash'})
    digest = hashlib.sha256(b'pack').hexdigest()
    remember(instance, source, digest)
    preserve_failed_source(instance, source, digest)
    controller = ImportRecoveryController(hub.parent(), hub, autostart=False)
    controller.timer.stop()
    controller.apply(pending(tmp_path))
    key = next(iter(controller.records))
    assert hub.ball._persistent_failure
    hub._close_tab(hub.tabs.indexOf(hub.tasks[key].page))
    unrelated = hub.begin_task('other')
    hub.finish_task(unrelated)
    assert hub.ball._persistent_failure
    controller.ignore(key)
    assert not hub.ball._persistent_failure
    assert (instance.parent/'_imports'/'Pack.json').exists()
    assert pending(tmp_path) == []
    controller.deleteLater()
