"""Spotlight walkthrough copy and targets, separate from its Qt renderer."""

from i18n import t


def first_game_steps():
    """Guide users to a first playable client without starting a download."""
    resources = t('RESOURCES')
    instances = t('MY_INSTANCES')
    settings = t('SETTINGS')
    return [
        {
            'route': [('maintab', resources)],
            'focus_main_tab': resources,
            'arrow': 'below',
            'text': '① 想开始一个新游戏，先来「下载新资源」。实例、整合包、Mod 和光影等资源都在这里。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '1')],
            'focus_resource_menu': 1,
            'arrow': 'below',
            'text': '② 进入「实例」。一个实例是一套独立的游戏，Mod、配置和存档可以与其他实例分开。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '1'),
                      ('widgetname', 'version_tree')],
            'focus_tree_item': '1.21.xx',
            'arrow': 'below',
            'text': '③ 先选 Minecraft 大版本。点「1.21.xx」这类大版本行，会自动选推荐的具体版：有黄金版本就选黄金版本，没有就选该系列最新正式版。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '1'),
                      ('widgetname', 'version_tree')],
            'focus_tree_item': '1.21.1',
            'arrow': 'below',
            'text': '④ 想自己挑具体版本，可展开大版本查看。例如「1.21.xx」里的「1.21.1 🏅」是黄金版本，Mod 生态通常更成熟；装特定 Mod 时仍要按它支持的版本选。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '1'),
                      ('widgetname', 'loader_panel')],
            'arrow': 'below',
            'text': '⑤ 只玩原版就选「原版」。想装 Mod，可先看看 Forge / NeoForge；大型内容整合包常见于这两个生态，但最终要按目标 Mod 或整合包要求选加载器。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '1'),
                      ('btn', '开始下载实例')],
            'arrow': 'above',
            'text': '⑥ 选好版本和加载器后，点「开始下载实例」。教程不会替你下载；完成后它会出现在「我的实例」。',
        },
        {
            'route': [('maintab', resources), ('rcswitch', '0')],
            'focus_resource_menu': 2,
            'arrow': 'below',
            'text': '⑦ 想省去逐个挑 Mod，可逛「整合包」；也能自己选 Mod、光影包、数据包和资源包。下载前记得确认目标实例与兼容版本。',
        },
        {
            'route': [('maintab', settings), ('btn', t('REPLAY_GUIDED_TUTORIAL'))],
            'arrow': 'above',
            'text': '⑧ 以后想重看这段引导，在「设置 → 系统」点「重播引导教程」就行。',
        },
        {
            'route': [('maintab', instances), ('btn', t('VERSION_HOME_LAUNCH_GAME'))],
            'arrow': 'above',
            'text': '⑨ 回到「我的实例」，选中刚下载的实例，再点「启动游戏」。现在可以开始玩了！',
        },
    ]
