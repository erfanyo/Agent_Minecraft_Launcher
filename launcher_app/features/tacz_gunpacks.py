# -*- coding: utf-8 -*-
'本体 TaCZ 枪包管理，安装对应 Mod 的实例自动显示。'
import os

FEATURE_ID = "tacz_gunpacks"
FEATURE_NAME = "枪包 (TACZ)"
FEATURE_DESCRIPTION = "管理永恒枪械工坊(TaCZ)的枪包目录:导入/删除枪包,打开目录。"
FEATURE_VERSION = "1.0.0"
FEATURE_API_VERSION = 1

#: 沿用核心原本的判定关键字(版本间 mod id 换过名字,tacz 只是最常见的一个)。
WATCH_MODS = ("tacz", "timeless_and_classics", "timeless", "tac_z")


def register(api):
    def build(ctx):
        from launcher_app.ui.pack_folder_ui import PackFolderPanel
        return PackFolderPanel(
            os.path.join(ctx.instance_dir, 'tacz', 'gunpack'),
            title='TACZ 枪包',
            unit='个',
            open_label='打开枪包目录',
            hint='枪包一般是「一个子文件夹一个包」,也可以直接丢 zip(会自动解压)。'
                 '进游戏后用枪械工坊的枪包管理器刷新即可。',
            on_status=ctx.status,
            open_dir=ctx.open_dir)

    api.register_instance_section('枪包(TACZ)', build, watch_mods=WATCH_MODS)
