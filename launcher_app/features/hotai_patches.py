# -*- coding: utf-8 -*-
'本体 Hotai 补丁只读查看，按实例中的相关 Mod 显示。'
import os

FEATURE_ID = "hotai_patches"
FEATURE_NAME = "Hotai 补丁查看"
FEATURE_DESCRIPTION = "只读列出实例 hotai/ 目录里已生效的 .badiff 补丁,方便确认补丁有没有打上。"
FEATURE_VERSION = "1.0.0"
FEATURE_API_VERSION = 1

WATCH_MODS = ("hotai",)


def register(api):
    def build(ctx):
        from launcher_app.ui.pack_folder_ui import PackFolderPanel
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
