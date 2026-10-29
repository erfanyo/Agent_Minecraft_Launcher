# -*- coding: utf-8 -*-
'测试用的可选插件目录导入助手；正式功能使用 launcher_app.features 的标准包导入。'
import os
import sys

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'plugins')


def ensure_plugin_path():
    """把 plugins/ 加入 sys.path(幂等),返回该目录。"""
    if PLUGIN_DIR not in sys.path:
        sys.path.insert(0, PLUGIN_DIR)
    return PLUGIN_DIR
