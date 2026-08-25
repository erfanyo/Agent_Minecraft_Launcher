# -*- coding: utf-8 -*-
"""
示例插件:演示 4 类注册点(AI工具 / GUI页面 / 设置项 / 技能)。
放在 plugins/ 下即被扫描装载;设置→插件 可启禁。

用途/学习:照这个文件改 = 你的 AI 生成新模块的最小模板。
"""
# 可选:插件元数据(供设置→插件页面展示;不提供也有默认)
PLUGIN_ID = "hello"
PLUGIN_NAME = "示例"
PLUGIN_DESCRIPTION = "演示注册一个 AI 工具 + 一个设置项 + 一个页面 + 一个技能(完整的插件示例)。"
PLUGIN_VERSION = "0.1.0"


# --- 全局:记录自定义设置值(插件内维护) ---
_HELLO_TAG = "hello"


def register(api):
    # 1) AI 工具
    def hello_action(args: dict):
        name = (args or {}).get("name", "玩家")
        return f"你好,{name}!这是「{api.plugin_id}」插件提供的 AI 工具。"

    api.register_tool(
        name="hello",
        description="示例工具:向用户打招呼。",
        parameters={"type": "object",
                    "properties": {"name": {"type": "string", "description": "称呼"}},
                    "required": []},
        handler=hello_action,
    )

    # 2) GUI 页面(章节)——挂到主 tab 里,这里演示为「示例页面」
    def build_page():
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("示例页面:插件注册的一个 GUI 页面。"))
        return w

    api.register_gui_page(label="示例页面", build_fn=build_page)

    # 2b) 独立设置页:在设置左菜单【单开一行】显示(按插件名)
    #     插件相关说明(能注册什么/能放什么)放这里讲,页面本身保持干净。
    def build_settings_page():
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("示例插件设置"))
        desc = QLabel("插件 = 启动器的可选功能模块。注册时会拿到一个 api,可以注册:\n"
                      "· AI 工具(供 AI 调用)\n"
                      "· GUI 页面/章节(build_fn 返回任意 QWidget,页面里可放任何控件)\n"
                      "· 设置项 / 独立设置页\n"
                      "· 技能(游戏生命周期钩子 + ai_hint)\n"
                      "照这个文件改,就是你的 AI 生成新插件的最小模板。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#8a93a0; font-size:11px;")
        lay.addWidget(desc)
        return w

    api.register_settings_page(build_settings_page)

    # 3) 设置项(占位登记)
    api.register_setting(
        key="greeting", description="打招呼文案", default="你好")

    # 4) 技能(Skill 子类,与内置技能同款接口:构造接收 manager,可挂生命周期钩子 + ai_hint)
    from skill_manager import Skill

    class HelloSkill(Skill):
        id = "hello_skill"
        name = "示例技能"
        description = "插件注册的示例技能。"
        category = "运行辅助"
        default_enabled = True

        def ai_hint(self):
            return ("【示例技能】插件加载成功。此技能可加游戏生命周期钩子"
                    "(on_game_start/on_game_log/on_game_stop)与 ai_hint。")

    api.register_skill(HelloSkill)
