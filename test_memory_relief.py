import os
import subprocess
import sys
import tempfile
import time
import unittest
import psutil
import shutil
from pathlib import Path
from memory_relief import pressure
from memory_policy import GIB


class ReliefTests(unittest.TestCase):
    def test_pressure_tiers_and_unknown(self):
        self.assertEqual(0, pressure(None, 6))
        self.assertEqual(0, pressure(10*GIB, 6))
        self.assertEqual(1, pressure(7*GIB, 6))
        self.assertEqual(2, pressure(6*GIB, 6))
        self.assertEqual(2, pressure(8*GIB, 4, 10))

    def test_child_survives_host_exit_and_can_write_output(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = os.path.join(folder, 'survived.txt')
            # A disposable host really exits before the child writes to inherited stdout.
            child = ("import os,time,pathlib;"
                     "pathlib.Path(" + repr(marker + '.pid') + ").write_text(str(os.getpid()));"
                     "time.sleep(.5);print('x'*100000);pathlib.Path(" + repr(marker) + ").write_text('ok')")
            host = "\n".join([
                'import sys',
                'from PySide6.QtCore import QCoreApplication',
                'from game_process_controller import GameProcessController',
                'app=QCoreApplication([])',
                'controller=GameProcessController()',
                f'controller.start([sys.executable,"-c",{child!r}],sys.executable,{folder!r},independent=True)',
                'controller.detach()',
            ])
            result = subprocess.run([sys.executable, '-c', host], capture_output=True, timeout=15)
            self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
            until = time.monotonic()+5
            while not os.path.exists(marker) and time.monotonic() < until:
                time.sleep(.1)
            self.assertTrue(os.path.isfile(marker), 'Child failed after host exit')
            # The marker is written before process exit. Wait for its cwd handle
            # to close before TemporaryDirectory deletes the Windows directory.
            with open(marker + '.pid', encoding='utf-8') as stream:
                child_pid = int(stream.read())
            try:
                psutil.Process(child_pid).wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            cleanup_root = Path(folder).resolve()
            self.assertEqual(cleanup_root.parent, Path(tempfile.gettempdir()).resolve())
            for attempt in range(20):
                try:
                    shutil.rmtree(cleanup_root)
                    break
                except OSError as error:
                    if getattr(error, 'winerror', None) not in (5, 32, 145) or attempt == 19:
                        raise
                    time.sleep(.1)


if __name__ == '__main__':
    unittest.main()
