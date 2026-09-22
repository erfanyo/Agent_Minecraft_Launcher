# -*- coding: utf-8 -*-
"""测试用的插件模块导入助手。

KubeJS 浏览/报错定位已改成插件(``plugins/kubejs_tools.py`` 与同目录的
``kubejs_viewer.py``)。插件目录不在 ``sys.path``(启动器是用
``importlib.util.spec_from_file_location`` 按文件加载的),所以测试里需要先把
插件目录挂上路径,才能像插件内部那样 ``import kubejs_viewer``。
"""
import os
import sys

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')


def ensure_plugin_path():
    """把 plugins/ 加入 sys.path(幂等),返回该目录。"""
    if PLUGIN_DIR not in sys.path:
        sys.path.insert(0, PLUGIN_DIR)
    return PLUGIN_DIR
