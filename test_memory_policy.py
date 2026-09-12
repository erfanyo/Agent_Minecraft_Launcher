import unittest
from unittest.mock import patch, Mock
import tempfile
from PySide6.QtWidgets import QApplication
from memory_policy import automatic_gb, automatic_budget, GIB
from memory_policy import track_process, history_peak
from memory_meter import MemoryMeter, memory_segments


class MemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_available_budget_and_bounds(self):
        self.assertEqual(1, automatic_gb(GIB // 2))
        self.assertEqual(1, automatic_gb(3 * GIB))
        self.assertEqual(2, automatic_gb(8 * GIB))
        self.assertEqual(2, automatic_gb(30 * GIB))
        with patch('memory_policy.snapshot', return_value=None):
            self.assertEqual(2, automatic_gb())

    def test_history_then_mods_then_extreme_reserve(self):
        normal = automatic_budget(32*GIB, 20*GIB, history_peak_bytes=5*GIB, mods=400)
        self.assertEqual(6, normal['gb'])
        self.assertIn('历史峰值', normal['basis'])
        unknown = automatic_budget(16*GIB, 12*GIB, mods=75)
        self.assertEqual(3, unknown['gb'])
        self.assertIn('75 个 Mod', unknown['basis'])
        extreme = automatic_budget(16*GIB, 12*GIB, mods=300)
        self.assertTrue(extreme['aggressive'])
        self.assertEqual(int(16*GIB*.07), extreme['reserve_bytes'])

    def test_segments_do_not_double_count(self):
        self.assertEqual((5, 3, 6, 2), memory_segments(16, 6, 3, 2, 6))
        self.assertEqual((5, 3, 2, 6), memory_segments(16, 6, 3, 2, 1))
        self.assertEqual((8, 0, 12, 0), memory_segments(16, 8, 0, 0, 12))

    def test_display_manual_auto_history(self):
        with patch('memory_meter.snapshot', return_value=(16*GIB, 8*GIB)), patch('memory_meter.history_peak', return_value=6*GIB):
            meter = MemoryMeter(lambda: 0, 'unused')
            self.assertEqual(6, meter.amount)
            self.assertIn('6.0 GB', meter.label.text())
            meter.resize(500, 180)
            self.assertFalse(meter.grab().isNull())
            meter.allocation = lambda: 12
            meter.refresh()
            self.assertEqual(12, meter.amount)
            self.assertIn('内存有点紧', meter.label.text())
            meter.deleteLater()

    def test_history_observes_java_process(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock(pid=123)
            process.poll.side_effect = [None, 0]
            target = Mock()
            target.memory_info.return_value.rss = 3*GIB
            with patch('psutil.Process', return_value=target), patch('memory_policy.time.sleep'):
                thread = track_process(process, directory)
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(3*GIB, history_peak(directory))


if __name__ == '__main__':
    unittest.main()
