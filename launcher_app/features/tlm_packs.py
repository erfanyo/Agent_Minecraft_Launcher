# -*- coding: utf-8 -*-
'本体车万女仆模型包管理，安装对应 Mod 的实例自动显示。'
import os

FEATURE_ID = "tlm_packs"
FEATURE_NAME = "车万女仆模型包"
FEATURE_DESCRIPTION = "管理 Touhou Little Maid 的自定义模型包目录:导入/删除模型包。"
FEATURE_VERSION = "1.0.0"
FEATURE_API_VERSION = 1

WATCH_MODS = ("touhou_little_maid", "touhoulittlemaid", "tlm")


def register(api):
    def build(ctx):
        from launcher_app.ui.pack_folder_ui import PackFolderPanel
        return PackFolderPanel(
            os.path.join(ctx.instance_dir, 'tlm_custom_pack'),
            title='车万女仆模型包',
            unit='套',
            open_label='打开模型包目录',
            hint='模型包是资源包结构(含 assets/ 与 pack.mcmeta),文件夹或 zip 都行;'
                 'zip 会自动解压。导错地方不会坏档,但游戏里不会出现,删掉即可。',
            on_status=ctx.status,
            open_dir=ctx.open_dir)

    api.register_instance_section('女仆模型包', build, watch_mods=WATCH_MODS)
