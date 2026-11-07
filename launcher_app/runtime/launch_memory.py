"""Launch memory estimates and window-readiness policy without UI dependencies."""
from dataclasses import dataclass
from enum import Enum
import re


def heap_limit(command):
    return next((int(match[1]) for arg in command
                 if (match := re.fullmatch(r'-Xmx(\d+)G', arg))), 2)


@dataclass(frozen=True)
class LaunchMemoryAssessment:
    state: object
    heap: int
    budget: dict
    level: int


def assess_launch_memory(command, history_dir, game_dir, *, sampler, budgeter,
                         history_reader, mod_counter, pressure_reader):
    state = sampler()
    heap = heap_limit(command)
    budget = budgeter(history_peak_bytes=history_reader(history_dir), mods=mod_counter(game_dir))
    level = pressure_reader(state[1] if state else None, heap, budget.get('desired_gb', 0))
    return LaunchMemoryAssessment(state, heap, budget, level)


class WindowReadiness(Enum):
    WAIT = 'wait'
    READY = 'ready'
    TIMED_OUT = 'timed_out'
    EXITED = 'exited'


class WindowReadinessTracker:
    def __init__(self, started_at, *, timeout=180, stable_seconds=10):
        self.started_at = started_at
        self.timeout = timeout
        self.stable_seconds = stable_seconds
        self.visible_since = None

    def observe(self, *, now, running, visible):
        if not running:
            return WindowReadiness.EXITED
        if now - self.started_at > self.timeout:
            return WindowReadiness.TIMED_OUT
        if not visible:
            self.visible_since = None
            return WindowReadiness.WAIT
        if self.visible_since is None:
            self.visible_since = now
        if now - self.visible_since >= self.stable_seconds:
            return WindowReadiness.READY
        return WindowReadiness.WAIT
