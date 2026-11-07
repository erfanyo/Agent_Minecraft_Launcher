"""Captured instance creation selections, usable by any frontend task runner."""
from copy import deepcopy
from launcher_app.instances.instance_install_service import InstanceInstallService


class InstanceCreateJob:
    def __init__(self, selection, game_root, version_isolation):
        self.selection = deepcopy(selection)
        self.game_root = game_root
        self.version_isolation = bool(version_isolation)

    def run(self, status, progress):
        selected = self.selection
        service = InstanceInstallService(lambda: self.game_root, lambda: self.version_isolation)
        return service.create_instance(
            selected['version'], selected['loader_key'], selected['modrinth_loader'],
            selected['shader'], selected['optimize'],
            loader_version=selected['loader_version'], shader_version=selected['shader_version'],
            optimize_versions=selected['optimize_versions'], fabric_api_version=selected.get('fabric_api_version'),
            status_cb=status, progress_cb=progress)
