# -*- coding: utf-8 -*-
"""窗口大小/位置记忆的逻辑单测(纯函数,不依赖真实窗口)。

覆盖容易出边界问题的几处:
- 非法/缺失记录 → 回默认尺寸并居中
- 记录落在已拔掉的显示器外 → 丢掉位置、只保留尺寸
- 记录比当前屏幕还大 → 收敛到屏幕大小
- 尺寸小于窗口最小尺寸 → 视为无效
"""
import unittest

import window_geometry as wg


class _Rect:
    def __init__(self, x, y, w, h):
        self._x, self._y, self._w, self._h = x, y, w, h

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._w

    def height(self):
        return self._h


class _Screen:
    def __init__(self, x, y, w, h):
        self._area = _Rect(x, y, w, h)

    def availableGeometry(self):
        return self._area


class SanitizeTests(unittest.TestCase):
    def test_accepts_valid(self):
        self.assertEqual(wg.sanitize({'x': 10, 'y': 20, 'w': 1024, 'h': 768}),
                         {'x': 10, 'y': 20, 'w': 1024, 'h': 768})

    def test_rejects_missing_keys(self):
        self.assertIsNone(wg.sanitize({'x': 1, 'y': 2}))
        self.assertIsNone(wg.sanitize({}))

    def test_rejects_non_dict(self):
        self.assertIsNone(wg.sanitize(None))
        self.assertIsNone(wg.sanitize('1280x860'))
        self.assertIsNone(wg.sanitize([1280, 860]))

    def test_rejects_non_numeric(self):
        self.assertIsNone(wg.sanitize({'x': 0, 'y': 0, 'w': 'wide', 'h': 800}))

    def test_rejects_too_small(self):
        """小于主窗口最小尺寸的记录不可用,避免恢复出一个挤扁的窗口。"""
        self.assertIsNone(wg.sanitize({'x': 0, 'y': 0, 'w': 100, 'h': 100}))

    def test_negative_position_allowed(self):
        """副屏在主屏左侧时 x 为负是正常的。"""
        self.assertEqual(wg.sanitize({'x': -1600, 'y': 0, 'w': 1280, 'h': 860}),
                         {'x': -1600, 'y': 0, 'w': 1280, 'h': 860})


class RestoreTargetTests(unittest.TestCase):
    def setUp(self):
        self.primary = _Screen(0, 0, 1920, 1080)
        self.screens = [self.primary]

    def test_missing_record_centers_default(self):
        target = wg.restore_target(None, self.screens, self.primary)
        self.assertEqual(target['w'], wg.DEFAULT_SIZE[0])
        self.assertGreaterEqual(target['x'], 0)
        self.assertGreaterEqual(target['y'], 0)

    def test_valid_record_is_kept(self):
        saved = {'x': 100, 'y': 80, 'w': 1200, 'h': 900}
        self.assertEqual(wg.restore_target(saved, self.screens, self.primary),
                         saved)

    def test_offscreen_position_is_dropped(self):
        """换显示器后旧位置可能在任何屏幕之外 → 不能把窗口留在看不见的地方。"""
        saved = {'x': 9000, 'y': 9000, 'w': 1200, 'h': 900}
        target = wg.restore_target(saved, self.screens, self.primary)
        self.assertEqual(target['w'], 1200)      # 尺寸保留
        self.assertEqual(target['h'], 900)
        self.assertLess(target['x'], 1920)       # 位置被拉回可见区域
        self.assertLess(target['y'], 1080)

    def test_secondary_screen_position_is_kept(self):
        """副屏上的窗口要能用,不能因为不在主屏就被判为不可见。"""
        screen2 = _Screen(-1600, 0, 1600, 900)
        saved = {'x': -1500, 'y': 50, 'w': 1200, 'h': 800}
        target = wg.restore_target(saved, [self.primary, screen2], self.primary)
        self.assertEqual(target, saved)

    def test_oversized_record_shrinks_to_screen(self):
        saved = {'x': 0, 'y': 0, 'w': 3000, 'h': 2000}
        target = wg.restore_target(saved, self.screens, self.primary)
        self.assertEqual(target['w'], 1920)
        self.assertEqual(target['h'], 1080)

    def test_shrunk_screen_keeps_minimum(self):
        """拔出大屏后剩个小屏:尺寸不能小于窗口最小值。"""
        small = _Screen(0, 0, 800, 600)
        saved = {'x': 0, 'y': 0, 'w': 1920, 'h': 1080}
        target = wg.restore_target(saved, [small], small)
        self.assertGreaterEqual(target['w'], wg.MIN_SIZE[0])
        self.assertGreaterEqual(target['h'], wg.MIN_SIZE[1])

    def test_no_screens_falls_back_gracefully(self):
        target = wg.restore_target({'x': 5, 'y': 5, 'w': 1000, 'h': 700}, [],
                                   None)
        self.assertEqual(target['w'], 1000)

    def test_default_geometry_matches_default_size_when_room(self):
        target = wg.default_geometry(self.screens, self.primary)
        self.assertEqual((target['w'], target['h']), wg.DEFAULT_SIZE)

    def test_default_geometry_clamped_on_small_screen(self):
        small = _Screen(0, 0, 1024, 768)
        target = wg.default_geometry([small], small)
        self.assertLessEqual(target['w'], 1024)
        self.assertLessEqual(target['h'], 768)


class CaptureTests(unittest.TestCase):
    class _Win:
        def __init__(self, maximized=False, minimized=False, full=False,
                     geom=(10, 20, 1000, 700)):
            self._max, self._min, self._full = maximized, minimized, full
            self._geom = geom

        def isMaximized(self):
            return self._max

        def isMinimized(self):
            return self._min

        def isFullScreen(self):
            return self._full

        def geometry(self):
            import types
            return types.SimpleNamespace(
                x=lambda: self._geom[0], y=lambda: self._geom[1],
                width=lambda: self._geom[2], height=lambda: self._geom[3])

    def test_captures_normal_window(self):
        self.assertEqual(wg.capture(self._Win()),
                         {'x': 10, 'y': 20, 'w': 1000, 'h': 700})

    def test_maximized_is_not_captured(self):
        """最大化时不能覆盖记录,否则「记住大小」会退化成每次最大化。"""
        self.assertIsNone(wg.capture(self._Win(maximized=True)))

    def test_minimized_is_not_captured(self):
        self.assertIsNone(wg.capture(self._Win(minimized=True)))

    def test_fullscreen_is_not_captured(self):
        self.assertIsNone(wg.capture(self._Win(full=True)))


if __name__ == '__main__':
    unittest.main()
