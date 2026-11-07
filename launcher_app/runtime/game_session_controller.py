"""Own game processes and route foreground/background lifecycle events.

No widgets, account access or instance-directory globals. Low-level process and
pipe handling remain in GameProcessController; views consume these signals.
"""
from PySide6.QtCore import QObject, Signal, Slot
from launcher_app.runtime.game_process_controller import GameProcessController


class GameSessionController(QObject):
    line_received = Signal(str)
    exited = Signal(int)
    background_exited = Signal()

    def __init__(self, parent=None, *, controller_factory=GameProcessController):
        super().__init__(parent)
        self._factory = controller_factory
        self._controllers = []
        self._current = self._create_controller()

    def _create_controller(self):
        controller = self._factory(self)
        controller.line_received.connect(self._line)
        controller.exited.connect(self._exited)
        self._controllers.append(controller)
        return controller

    @property
    def controllers(self):
        return tuple(self._controllers)

    @property
    def running_processes(self):
        return tuple(controller.process for controller in self._controllers if controller.is_running)

    def start(self, command, java_exe, cwd, *, independent=False):
        previous = self._current
        controller = self._create_controller() if previous.is_running else previous
        try:
            process = controller.start(command, java_exe, cwd, independent=independent)
        except Exception:
            if controller is not previous:
                self._controllers.remove(controller)
                controller.deleteLater()
            raise
        self._current = controller
        return process

    @Slot(str)
    def _line(self, line):
        if self.sender() is self._current:
            self.line_received.emit(line)

    @Slot(int)
    def _exited(self, code):
        if self.sender() is self._current:
            self.exited.emit(code)
        else:
            self.background_exited.emit()

    def detach(self):
        """Stop forwarding while allowing games to keep running."""
        for controller in self._controllers:
            controller.detach()
