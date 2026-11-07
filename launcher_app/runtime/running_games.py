"""Resolve owned and externally detected running games without any UI objects."""
import os
import psutil


def _visible_window(pid):
    from launcher_app.runtime.memory_relief import visible_game_window
    return visible_game_window(pid)


class RunningGames:
    def __init__(self, *, windows=None, pid_exists=psutil.pid_exists,
                 create_time=None, visible_window=_visible_window):
        self._windows = os.name == 'nt' if windows is None else windows
        self._pid_exists = pid_exists
        self._create_time = create_time or (lambda pid: psutil.Process(pid).create_time())
        self._visible_window = visible_window
        self._owned = {}
        self._seen_windows = set()
        self._detected = []

    def register(self, pid, instance_id):
        self._owned[pid] = instance_id
        self._seen_windows.discard(pid)

    def set_detected(self, clients):
        self._detected = list(clients)

    def _window_open(self, pid, owned=False):
        if not self._pid_exists(pid):
            return False
        if not self._windows:
            return True
        if self._visible_window(pid):
            self._seen_windows.add(pid)
            return True
        # A launch counts during loading; a previously seen, closed window doesn't.
        return owned and pid not in self._seen_windows

    def live(self, owned_processes):
        for client in self._detected:
            if client.get('window_visible', True):
                for parent_pid in client.get('parent_pids', []):
                    if self._owned.get(parent_pid) == client['id']:
                        self._seen_windows.add(parent_pid)
        live = {process.pid: self._owned.get(process.pid, '')
                for process in owned_processes if self._window_open(process.pid, owned=True)}
        for client in self._detected:
            try:
                created = self._create_time(client['pid'])
                if created != client.get('create_time', created):
                    continue
            except psutil.Error:
                continue
            if client['pid'] in self._owned and client['pid'] not in live:
                continue
            if self._window_open(client['pid']):
                live.setdefault(client['pid'], client['id'])
        return live
