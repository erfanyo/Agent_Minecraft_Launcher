# -*- coding: utf-8 -*-
"""Create 投影原理图插件:管理实例 ``schematics/`` 下的 ``.nbt`` 蓝图。

**注意两个目录**:这里管的是**实例级**的 ``schematics/``;存档内的原理图在
``<存档>/schematics/``,归存档管,不在这里。提示语里写清楚了,免得用户找不到。
"""
import os

PLUGIN_ID = "create_schematics"
PLUGIN_NAME = "投影原理图 (Create)"
PLUGIN_DESCRIPTION = "管理机械动力(Create)的投影原理图目录:导入/删除 .nbt,打开目录。"
PLUGIN_VERSION = "1.0.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

#: create 这个关键字在文件名里出现得非常普遍(create-fabric、createbigcannons…),
#: 口径与核心原来的 `_has_mod("create")` 完全一致。
WATCH_MODS = ("create",)


def register(api):
    def build(ctx):
        from pack_folder_ui import PackFolderPanel
        return PackFolderPanel(
            os.path.join(ctx.instance_dir, 'schematics'),
            title='投影原理图(Create)',
            exts=('.nbt',),
            unit='张',
            open_label='打开原理图目录',
            hint='原理图(.nbt)放进这个实例级 schematics 目录;进游戏手持蓝图 + Ctrl '
                 '(工程师护目镜)选图即可。注:存档内的原理图在 <存档>/schematics/,'
                 '那一份不在这里。',
            on_status=ctx.status,
            open_dir=ctx.open_dir)

    api.register_instance_section('投影原理图', build, watch_mods=WATCH_MODS)
