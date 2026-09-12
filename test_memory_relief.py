import os
import subprocess
import sys
import tempfile
import time
import unittest
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
            child = "import time,pathlib;time.sleep(.5);print('x'*100000);pathlib.Path(" + repr(marker) + ").write_text('ok')"
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


if __name__ == '__main__':
    unittest.main()
