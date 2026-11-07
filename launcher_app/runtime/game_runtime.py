"""Started-game bookkeeping and evidence, independent of frontend controls."""
from dataclasses import dataclass
import os
import time
from launcher_app.instances.crash_diagnostics import GameRunEvidence
from launcher_app.runtime.memory_policy import track_process


@dataclass(frozen=True)
class StartedGame:
    process: object
    instance_id: str
    runtime_id: str
    game_root: str
    evidence: GameRunEvidence
    history_dir: str


class GameRuntime:
    def __init__(self, sessions, registry, remember_instance, *, track=track_process, clock=time.time):
        self.sessions, self.registry = sessions, registry
        self._remember_instance, self._track, self._clock = remember_instance, track, clock
        self.current = None

    def start(self, plan, version, game_root, *, independent=False):
        started_at = self._clock()
        process = self.sessions.start(plan.command, plan.java_exe, plan.game_dir, independent=independent)
        root = getattr(plan, 'game_root', None) or game_root
        launched = StartedGame(process, version['id'], plan.detail['id'], root,
                               GameRunEvidence(plan.game_dir, started_at),
                               os.path.join(root, 'versions', version['id']))
        self.registry.register(process.pid, launched.runtime_id)
        self.current = launched
        return launched

    def record_started(self, settings):
        if self.current is None:
            return
        launched = self.current
        self._track(launched.process, launched.history_dir)
        if settings.get('last_played_instance') != launched.instance_id:
            settings['last_played_instance'] = launched.instance_id
            try:
                self._remember_instance(launched.instance_id)
            except Exception:
                pass

    def has_crash(self):
        return bool(self.current and self.current.evidence.has_crash())

    def crash_report(self, code):
        if self.current is None:
            raise RuntimeError('没有可用的游戏启动记录')
        return self.current.evidence.report(code)
