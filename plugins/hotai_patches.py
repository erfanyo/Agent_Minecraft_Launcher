# -*- coding: utf-8 -*-
"""Hotai 补丁查看插件(只读):列出实例 ``hotai/`` 里已经生效的 ``.badiff`` 补丁。

**为什么只读**:``hotai/`` 不是「丢文件进去」的目录,而是 mod 自己生成的
**类路径树**(``com/github/<作者>/<包>/<类>.badiff``,一个类一个文件)。往里
手工丢文件没有意义,删文件更是直接让补丁失效——所以这里只列、只报告,不提供
导入/删除,也不允许拖放(见 docs/PLUGIN_IDEAS.md 的落地记录)。
"""
import os

PLUGIN_ID = "hotai_patches"
PLUGIN_NAME = "Hotai 补丁查看"
PLUGIN_DESCRIPTION = "只读列出实例 hotai/ 目录里已生效的 .badiff 补丁,方便确认补丁有没有打上。"
PLUGIN_VERSION = "1.0.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

WATCH_MODS = ("hotai",)


def register(api):
    def build(ctx):
        from pack_folder_ui import PackFolderPanel
        return PackFolderPanel(
            os.path.join(ctx.instance_dir, 'hotai'),
            title='Hotai 补丁',
            exts=('.badiff',),
            unit='个补丁',
            open_label='打开 hotai 目录',
            recursive=True,
            read_only=True,
            hint='这些 .badiff 是 mod 按「类的完整路径」生成的补丁文件,由 mod 自己维护。'
                 '如果某个类缺少补丁,进游戏时会报「找不到函数」之类的错误——'
                 '把对应的补丁文件补进 hotai 目录即可(目录结构要与类路径一致)。',
            on_status=ctx.status,
            open_dir=ctx.open_dir)

    api.register_instance_section('Hotai 补丁', build, watch_mods=WATCH_MODS)
