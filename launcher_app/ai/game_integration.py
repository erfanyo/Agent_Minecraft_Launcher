"""Coordinate game-side AI, skills and inference relief through explicit ports."""
from dataclasses import dataclass
from typing import Callable
from launcher_app.ai.in_game_ai import InGameAI, make_answerer


@dataclass
class GameIntegrationPorts:
    stop_local_engine: Callable
    game_running: Callable
    game_stopped: Callable
    skill_started: Callable
    skill_stopped: Callable
    skill_log: Callable
    show_status: Callable


class GameIntegration:
    def __init__(self, ports, *, bridge_factory=InGameAI, answerer_factory=make_answerer):
        self.ports = ports
        self._bridge_factory = bridge_factory
        self._answerer_factory = answerer_factory
        self.bridge = None

    @staticmethod
    def mode(settings):
        return str(settings.get('ai_in_game','off') or 'off').strip().lower()

    def before_launch(self, settings):
        if self.mode(settings) == 'off':
            self.ports.stop_local_engine()

    def start_bridge(self, instance_id, settings, game_root, context):
        self.stop_bridge()
        if self.mode(settings) == 'off':
            return
        try:
            # Context is a snapshot captured by the GUI, never a worker UI read.
            answerer = self._answerer_factory(settings=settings, context_provider=lambda: context)
            bridge = self._bridge_factory(instance_id, answerer, poll=1.0, game_dir=game_root)
            bridge.start()
            self.bridge = bridge
            self.ports.show_status(f'游戏内 AI 已开启({instance_id}),进游戏敲 /ai 试试')
        except Exception as exc:
            self.ports.show_status(f'游戏内 AI 启动失败: {type(exc).__name__}: {exc}')

    def started(self, process, instance_id, settings, game_root, context):
        self.start_bridge(instance_id, settings, game_root, context)
        self.ports.skill_started(process, instance_id)
        try:
            self.ports.game_running(process)
        except Exception:
            pass

    def stopped(self, code, remaining_process=None):
        self.ports.skill_stopped(code)
        try:
            if remaining_process is None:
                self.ports.game_stopped()
            else:
                self.ports.game_running(remaining_process)
        except Exception:
            pass
        self.stop_bridge()

    def log(self, line):
        self.ports.skill_log(line)

    def stop_bridge(self):
        if self.bridge is not None:
            try:
                self.bridge.stop()
            except Exception:
                pass
            self.bridge = None
