"""Repeatable visual artifacts, not cross-platform pixel baselines."""
import json
from pathlib import Path

import pytest
from launcher_app.ui.ui_tokens import set_theme_mode
from launcher_app.ui.ui_style import refresh_theme

pytestmark = pytest.mark.ui


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('scene', ['multiple-tasks', 'confirmation', 'failed-task', 'inline-validation'])
def test_visual_scene(hub, qtbot, request, theme, scene):
    set_theme_mode(theme)
    refresh_theme()
    first = hub.begin_task('下载资源')
    hub.update_task(first, message='正在下载 Fabric API…', done=2, total=5)
    second = hub.begin_task('导出服务端')
    hub.update_task(second, message='第 2 轮测试，已停用 1 个客户端 Mod。')
    if scene == 'inline-validation':
        from launcher_app.ui.ui_notifications import inline_notice
        target = inline_notice(hub.parent(), '名称不可用', '请输入另一个实例名称。')
    elif scene == 'confirmation':
        hub.request_confirmation(second, '服务端准备完成', '文件已准备好。现在开始隔离启动测试吗？',
                                 [('开始测试', True), ('直接打包', False)], lambda _: None)
        target = hub.card
    else:
        if scene == 'failed-task':
            hub.finish_task(second, 'failed', '模拟安装失败，可以检查日志后重试。')
        hub.show_task(second)
        target = hub.details
    qtbot.waitUntil(target.isVisible)
    folder = Path(request.config.getoption('--ui-artifacts')) / 'scenes'
    folder.mkdir(parents=True, exist_ok=True)
    stem = f'{theme}-{scene}'
    assert target.grab().save(str(folder / (stem + '.png')))
    (folder / (stem + '.json')).write_text(json.dumps({
        'theme': theme, 'scene': scene, 'width': target.width(), 'height': target.height(),
        'devicePixelRatio': target.devicePixelRatioF(), 'tasks': hub.tabs.count(),
    }, indent=2), encoding='utf-8')
