# -*- coding: utf-8 -*-
'本体 YSM 皮肤管理，安装对应 Mod 的实例自动显示。'
import os

FEATURE_ID = "ysm_skins"
FEATURE_NAME = "皮肤 (YSM)"
FEATURE_DESCRIPTION = ("管理 Yes Steve Model 的皮肤目录:导入/删除皮肤,"
                      "打开实例的 ysm 文件夹。")
FEATURE_VERSION = "1.0.0"
FEATURE_API_VERSION = 1

#: 装了其中之一就在实例详情里出现「皮肤(YSM)」分区。
#: 与旧硬编码的判定口径一致(instance_manager 原来就是这么写死的)。
WATCH_MODS = ("ysm", "yes_steve_model", "yesstevemodel", "yes-steve-model")


def register(api):
    def build(ctx):
        from launcher_app.ui.pack_folder_ui import PackFolderPanel
        return PackFolderPanel(
            os.path.join(ctx.instance_dir, 'ysm'),
            title='YSM 皮肤',
            exts=('.png', '.model', '.json'),
            unit='张',
            open_label='打开皮肤目录',
            hint='皮肤由「.png 贴图 + 模型绑定文件」组成,直接把皮肤文件或整个皮肤'
                 '压缩包丢进来即可(支持拖放)。进游戏后按 H 打开 YSM 界面穿戴。',
            on_status=ctx.status,
            open_dir=ctx.open_dir)

    api.register_instance_section('皮肤(YSM)', build, watch_mods=WATCH_MODS)
