"""Instance filesystem actions; UI confirmation is the caller's responsibility."""
from dataclasses import dataclass
import os
import shutil
from launcher_app.core.safe_paths import safe_child, safe_component


@dataclass(frozen=True)
class ClearInstancesResult:
    removed: tuple
    failures: tuple


class InstanceActions:
    def __init__(self, game_root):
        self.game_root = os.path.abspath(game_root)

    @staticmethod
    def _reject_link(path):
        if os.path.islink(path) or getattr(os.path, 'isjunction', lambda _: False)(path):
            raise ValueError('实例安装目录是链接，请先检查其实际位置')

    def _versions(self):
        folder = os.path.join(self.game_root, 'versions')
        self._reject_link(folder)
        return safe_child(self.game_root, 'versions')

    def _installation(self, instance_id):
        safe_component(instance_id)
        versions = self._versions()
        raw = os.path.join(versions, instance_id)
        self._reject_link(raw)
        return safe_child(versions, instance_id)

    def delete(self, instance_id):
        folder = self._installation(instance_id)
        if os.path.isdir(folder):
            shutil.rmtree(folder)

    def clear_all(self):
        versions = self._versions()
        if not os.path.isdir(versions):
            return ClearInstancesResult((), ())
        removed, failures = [], []
        for name in os.listdir(versions):
            if not os.path.isdir(os.path.join(versions, name)):
                continue
            try:
                self.delete(name)
                removed.append(name)
            except (OSError, ValueError) as exc:
                failures.append((name, str(exc)))
        return ClearInstancesResult(tuple(removed), tuple(failures))

    def rename(self, instance_id, name):
        from launcher_app.instances.instance_metadata import rename_instance
        name = name.strip()
        rename_instance(self.game_root, instance_id, name)
        return name

    def backup(self, instance_id):
        from launcher_app.core.backup import backup_instance
        return backup_instance(instance_id, self.game_root)
