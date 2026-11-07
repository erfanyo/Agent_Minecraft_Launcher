"""Captured command-bridge requests shared by UI adapters and tests."""
from dataclasses import dataclass
from copy import deepcopy
import os


@dataclass(frozen=True)
class CommandSetupRequest:
    instance_id: str
    game_dir: str
    loader: str
    game_version: str

    @classmethod
    def capture(cls, instance, game_dir):
        instance = deepcopy(instance)
        return cls(instance['id'], os.path.abspath(game_dir), instance.get('loader') or '', instance['base'])

    def check_bridge(self, _task=None):
        from launcher_app.core import bridge_mod_dist
        status = bridge_mod_dist.check_bridge_mod(self.game_dir, self.loader, self.game_version)
        info = bridge_mod_dist.bridge_mod_info(self.loader, self.game_version) if status == 'not_installed' else None
        return {'status': status, 'info': info}

    def install_bridge(self, status_cb, progress_cb):
        from launcher_app.core import bridge_mod_dist
        try:
            filename = bridge_mod_dist.download_bridge_mod(self.game_dir, self.loader, self.game_version,
                                                          progress_callback=progress_cb)
        except Exception as exc:
            raise RuntimeError(f'下载失败:{exc}') from exc
        status_cb(f'bridge-mod 已安装:{filename}\n重进世界后即可用本地指令口(无需对局域网开放)。')

    def install_lan_properties(self, status_cb, progress_cb):
        from launcher_app.resources.modrinth import download_mod
        from launcher_app.instances.game_command import ensure_rcon_config
        try:
            filename = download_mod('lan-server-properties', self.game_version, self.loader,
                                    os.path.join(self.game_dir, 'mods'), progress_callback=progress_cb)
        except Exception as exc:
            raise RuntimeError(f'下载失败:{exc}') from exc
        if not filename:
            status_cb(f'没有 {self.game_version}+{self.loader} 的版本,换个版本试试')
            return False
        config = ensure_rcon_config(self.game_dir)
        status_cb(f'Lan Server Properties 已安装:{filename}\n{config}')

    def install_online(self, slug, status_cb, progress_cb):
        from launcher_app.runtime.online_mods import install_online_mod
        message = install_online_mod(slug, self.game_version, self.loader,
                                     os.path.join(self.game_dir, 'mods'), progress_callback=progress_cb)
        status_cb(message)
