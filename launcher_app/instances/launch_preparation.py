"""A captured launch request, independent of windows and task runners."""
from copy import deepcopy
from dataclasses import dataclass
import os

from launcher_app.instances.game_launch_service import GameLaunchService


@dataclass(frozen=True)
class LaunchRequest:
    version: dict
    settings: dict
    game_root: str
    runtime_root: str

    @classmethod
    def capture(cls, version, settings, game_root, runtime_root):
        # The worker must not observe later edits to settings or selection.
        return cls(deepcopy(version), deepcopy(settings), game_root, runtime_root)

    def game_dir_for(self, identity):
        return (os.path.join(self.game_root, 'versions', identity)
                if self.settings.get('version_isolation') else self.game_root)

    def prepare(self, status_cb=None, progress_cb=None, *, credentials_writer=None):
        if credentials_writer is None:
            from launcher_app.core.accounts import update_refreshed_microsoft_credentials
            credentials_writer = update_refreshed_microsoft_credentials
        service = GameLaunchService(
            lambda: self.game_root, lambda: self.runtime_root, lambda: self.settings,
            lambda changed: credentials_writer(
                (self.settings.get('ms_credentials') or {}).get('uuid', ''),
                changed.get('ms_credentials', {})),
            self.game_dir_for,
        )
        return service.prepare(self.version, status_cb=status_cb, progress_cb=progress_cb)
