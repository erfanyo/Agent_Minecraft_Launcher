# -*- coding: utf-8 -*-
"""
插件系统(骨架):让启动器的功能以「插件」形式存在,并让 AI 能扩展。

设计目标(来自「一切皆插件」):
1. 现有**非核心/可选功能**可作为插件注册、卸载(设置→插件 列出来,可启禁);
   核心组件(启动/实例/下载/设置/AI)不插件化,保持稳定。
2. 插件 = `plugins/<名字>.py`,提供 `register(api)` 函数,在启动时被扫描装载(静态加载)。
   支持 4 类注册点:AI 工具 / GUI 页面(章节)/ 设置项 / 技能(Skill)。
3. 插件启停状态存设置 `settings["plugins_disabled"]`(默认全开);禁用则不装载其注册内容。

设计原则:
- **对既有代码零侵入**:插件通过 api 回调把「注册内容」登记进全局 registry,
  由既有消费方(工具/页面/设置/技能)在需要时读取;不改造原有内部逻辑。
- **安全**:插件是本地代码,信任模型和 AI 工具/技能类似(本地可信)。未来可加
  权限/沙箱(复用 ai_actions),当前先记录。

plugin_api: 每个插件注册时收到的 api 对象,见下方 build_api();它把各注册点的
「登记函数」暴露给插件,插件调用后写入全局 registry。
"""
import importlib.util
import os

# plugins 目录(启动器私有数据,不进 git;模板/示例可放仓库根 plugins_templates)
PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")

# ---------------- 全局注册表(插件登记的内容) ----------------
# 各注册点 = {} 或 [],由消费方读取;插件 register() 时写入。
TOOLS = {}            # name -> (描述, 参数schema, 处理函数)  (AI 工具)
GUI_PAGES = {}        # label -> build_fn(返回 QWidget)        (GUI 章节,挂到某页/主菜单)
SETTINGS = {}         # key -> {description, ...}              (设置项,占位登记)
SKILLS = []           # [Skill子类]                            (技能)


class PluginAPI:
    """插件注册时拿到的 api,提供各注册点的登记函数。"""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id

    def register_tool(self, name, description, parameters, handler):
        """AI 工具。name 会加前缀 <插件id>__ 防冲突。handler(args_dict)->str。"""
        full = f"{self.plugin_id}__{name}"
        TOOLS[full] = (description, parameters, handler)

    def register_gui_page(self, label, build_fn):
        """GUI 页面/章节。build_fn() 返回 QWidget;label 是菜单/标签名。"""
        GUI_PAGES[label] = build_fn

    def register_setting(self, key, description, default=None, choices=None):
        """设置项(占位登记;实际读写由插件 via get/set)。"""
        SETTINGS[self.plugin_id + "." + key] = {
            "description": description, "default": default, "choices": choices}

    def register_skill(self, skill_cls):
        """技能(Skill 子类,与 skill_manager.BUILTIN_SKILLS 同款接口)。"""
        SKILLS.append(skill_cls)


def build_api(plugin_id: str) -> PluginAPI:
    return PluginAPI(plugin_id)


def discover_plugins() -> list:
    """返回 plugins/ 下所有可用插件(名, 路径)。忽略非 .py、以下划线开头的。"""
    result = []
    if not os.path.isdir(PLUGIN_DIR):
        return result
    for f in sorted(os.listdir(PLUGIN_DIR)):
        if f.endswith(".py") and not f.startswith("_"):
            result.append((f[:-3], os.path.join(PLUGIN_DIR, f)))
    return result


def _load_plugin_module(path: str):
    """从文件路径 import 插件模块(用唯一模块名,避免缓存冲突)。"""
    modname = "_amcl_plugin_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        return None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_plugin(name: str, path: str, disabled: set) -> bool:
    """装载一个插件:调用其 register(api) 登记内容。
    disabled:插件 id 集合(被禁用则跳过)。返回是否装载成功。"""
    if name in disabled:
        return False
    mod = _load_plugin_module(path)
    if mod is None or not hasattr(mod, "register"):
        return False
    try:
        mod.register(build_api(name))
        return True
    except Exception:
        return False


def load_all(disabled: set | None = None) -> dict:
    """启动时装载所有插件。disabled = 被禁用的插件 id 集合。
    返回 {插件名: bool(是否装载)}。清空全局注册表后再扫。"""
    global TOOLS, GUI_PAGES, SETTINGS, SKILLS
    TOOLS, GUI_PAGES, SETTINGS, SKILLS = {}, {}, {}, []
    disabled = set(disabled or [])
    loaded = {}
    for name, path in discover_plugins():
        loaded[name] = load_plugin(name, path, disabled)
    return loaded


def settings_has(settings: dict, key: str) -> bool:
    return bool(settings.get(key))
