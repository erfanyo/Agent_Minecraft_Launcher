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
PLUGIN_VERSION = "0.2.0"
PLUGIN_API_VERSION = 1
PLUGIN_DEFAULT_ENABLED = False

from ui_style import muted_color


def register(api):
    # 1) AI 工具
    def hello_action(args: dict):
        name = (args or {}).get("name", "玩家")
        greeting = str(api.get_config("greeting", "你好") or "你好").strip()
        return f"{greeting},{name}!这是「{api.plugin_id}」插件提供的 AI 工具。"

    api.register_tool(
        name="hello",
        description="示例工具:向用户打招呼。",
        parameters={"type": "object",
                    "properties": {"name": {"type": "string", "description": "称呼"}},
                    "required": []},
        handler=hello_action,
    )

    # 2) 主标签页:与 下载新资源/联机/设置 平级(演示插件能注册全新的主 tab)
    def build_main_tab():
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("示例标签页:插件注册的一个【主标签页】(和「下载新资源」「设置」平级)。"))
        api.bind_ai_context(
            w, "overview", "Hello 示例插件",
            "这是插件 API 的演示页面。提供 hello 打招呼工具，支持自定义问候文案。",
            provider=lambda: "当前问候文案：" + str(api.get_config("greeting", "你好")))
        return w

    api.register_main_tab(label="示例标签", build_fn=build_main_tab)

    # 3) 独立设置页:在设置左菜单【单开一行】显示(按插件名)
    #     插件相关说明(能注册什么/能放什么)放这里讲,页面本身保持干净。
    def build_settings_page():
        from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                                       QVBoxLayout, QWidget)
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
        desc.setStyleSheet(f"color: {muted_color()}; font-size:11px;")
        lay.addWidget(desc)
        row = QHBoxLayout()
        row.addWidget(QLabel("打招呼文案:"))
        greeting = QLineEdit(str(api.get_config("greeting", "你好") or "你好"))
        save = QPushButton("保存")
        row.addWidget(greeting, 1)
        row.addWidget(save)
        lay.addLayout(row)
        hint = QLabel("")
        hint.setStyleSheet(f"color: {muted_color()}; font-size:11px;")
        lay.addWidget(hint)

        def save_greeting():
            value = greeting.text().strip() or "你好"
            api.set_config("greeting", value)
            greeting.setText(value)
            hint.setText("已保存；下次 AI 调用“hello”会使用这句文案。")

        save.clicked.connect(save_greeting)
        lay.addStretch()
        return w

    api.register_settings_page(build_settings_page)

    # 4) 设置值通过 api.get_config / api.set_config 保存，不依赖核心内部设置结构。

    # 5) 技能(Skill 子类,与内置技能同款接口:构造接收 manager,可挂生命周期钩子 + ai_hint)
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
