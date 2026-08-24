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

**许可证约定(独立作品 vs 派生作品)**:
- 启动器本体 = AGPL-3.0;作者自研插件也随启动器走 AGPL-3.0(以后可能换 GPL)。
- 第三方插件 = **各作者自定许可**(可 MIT/Apache/闭源)。因为插件通过**公开 API(register)**
  独立注册内容、不被要求改动核心,属**独立作品(mere aggregation)**,AGPL 传播性不传染到它。
- 若插件修改/派生启动器核心(改内部实现/共享深层),则必须 AGPL。守住分界线:
  插件只依赖 `api` 与 PySide6,不 import 启动器内部模块改行为、不 monkeypatch 核心类。


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
LANGUAGE_PACKS = {}   # pack_id -> {"name", "pack"}            (语言包:文本覆盖)

# ---- 插件元数据(从插件模块读取):默认启禁 / 独立设置页 ----
# discover_plugins 返回 [(name, path, meta)];meta 含 default_enabled / has_settings / settings_page
_PLUGIN_META = {}     # name -> {default_enabled(bool), settings_build_fn(callable|None), name, description}


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

    def register_settings_page(self, build_fn):
        """为插件注册一个【独立设置页】(build_fn() 返回 QWidget)。
        设置左菜单会为它单开一行(按插件名)。"""
        _PLUGIN_META.setdefault(self.plugin_id, {})
        _PLUGIN_META[self.plugin_id]["settings_build_fn"] = build_fn

    def register_language_pack(self, pack_id: str, name: str, pack: dict, lang: str = ""):
        """语言包:用 {"原文": "替换文本"} 覆盖启动器所有文本(第三方/玩梗语言)。
        注册进 i18n;若当前语言(id 未指定)则立即可选。"""
        LANGUAGE_PACKS[pack_id] = {"name": name, "pack": dict(pack or {}), "lang": lang}
        try:
            import i18n
            i18n.register_pack(pack_id, name, pack, lang)
        except Exception:
            pass


def build_api(plugin_id: str) -> PluginAPI:
    return PluginAPI(plugin_id)


def _read_plugin_meta(mod) -> dict:
    """从插件模块读元数据:PLUGIN_NAME/PLUGIN_DESCRIPTION/PLUGIN_DEFAULT_ENABLED。"""
    try:
        default_enabled = bool(getattr(mod, "PLUGIN_DEFAULT_ENABLED", True))
    except Exception:
        default_enabled = True
    return {
        "name": getattr(mod, "PLUGIN_NAME", None),
        "description": getattr(mod, "PLUGIN_DESCRIPTION", ""),
        # 注意:register() 里的 register_settings_page 会写入 _PLUGIN_META[name]["settings_build_fn"]
        "default_enabled": default_enabled,
    }


def discover_plugins() -> list:
    """返回 plugins/ 下所有可用插件 [(name, path)]。忽略非 .py、以下划线开头的。"""
    result = []
    if not os.path.isdir(PLUGIN_DIR):
        return result
    for f in sorted(os.listdir(PLUGIN_DIR)):
        if f.endswith(".py") and not f.startswith("_"):
            result.append((f[:-3], os.path.join(PLUGIN_DIR, f)))
    return result


def discover_plugins_meta() -> dict:
    """扫描插件,返回 {name: {default_enabled, name, description, has_settings}}。
    只读插件模块元数据;has_settings 通过 inspect register 里是否调用 register_settings_page 判断。
    不污染全局 registry(_PLUGIN_META / TOOLS 等)。"""
    meta_out = {}
    for name, path in discover_plugins():
        base = {"default_enabled": True, "name": name, "description": "", "has_settings": False}
        try:
            mod = _load_plugin_module(path)
            m = _read_plugin_meta(mod)
            # 用隔离的临时容器测"是否注册了设置页":替换 plugin 模块看到的全局注册表,
            # 避免 register 的副作用(工具/页面/技能/语言包)泄漏到真实 registry。
            import plugin_manager as _pm
            saved = (_pm.TOOLS, _pm.GUI_PAGES, _pm.SETTINGS, _pm.SKILLS,
                     _pm.LANGUAGE_PACKS, _pm._PLUGIN_META)
            try:
                _pm.TOOLS, _pm.GUI_PAGES, _pm.SETTINGS = {}, {}, {}
                _pm.SKILLS, _pm.LANGUAGE_PACKS, _pm._PLUGIN_META = [], {}, {}
                # 也隔离 i18n 语言包注册(register_language_pack 会写 i18n)
                try:
                    import i18n as _i18n
                    _saved_i18n = dict(_i18n._PACKS)
                    _i18n._PACKS.clear()
                except Exception:
                    _saved_i18n = None
                if hasattr(mod, "register"):
                    mod.register(build_api(name))
                m["has_settings"] = bool(_pm._PLUGIN_META.get(name, {}).get("settings_build_fn"))
            finally:
                (_pm.TOOLS, _pm.GUI_PAGES, _pm.SETTINGS, _pm.SKILLS,
                 _pm.LANGUAGE_PACKS, _pm._PLUGIN_META) = saved
                try:
                    if _saved_i18n is not None:
                        import i18n as _i18n
                        _i18n._PACKS.clear()
                        _i18n._PACKS.update(_saved_i18n)
                except Exception:
                    pass
            m["name"] = m["name"] or name
            meta_out[name] = m
        except Exception:
            meta_out[name] = base
        meta_out[name].setdefault("description", "")
    return meta_out


def plugin_settings_page(name: str):
    """返回某插件注册的独立设置页 build_fn(None=没有)。"""
    meta = _PLUGIN_META.get(name, {})
    return meta.get("settings_build_fn")


def plugin_is_disabled(settings: dict, name: str) -> bool:
    """判断插件当前是否被禁用:设置里显式禁用,或没标记但插件默认关闭(PLUGIN_DEFAULT_ENABLED=False)。"""
    disabled = set(settings.get("plugins_disabled", []) or [])
    if name in disabled:
        return True
    # 没禁用但插件默认关闭(且用户没显式启用):通过 plugins_enabled 白名单判断
    # 逻辑见 load_all:默认关但未启用 => 禁用
    return False


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


def load_all(settings: dict | None = None, disabled: set | None = None) -> dict:
    """启动时装载所有插件。disabled = 被禁用的插件 id 集合(显式禁用)。
    额外考虑"默认关闭"插件:PLUGIN_DEFAULT_ENABLED=False 且未被显式启用(settings['plugins_enabled'])
    的插件不装载。返回 {插件名: bool(是否装载)}。清空全局注册表后再扫。"""
    global TOOLS, GUI_PAGES, SETTINGS, SKILLS, LANGUAGE_PACKS, _PLUGIN_META
    TOOLS, GUI_PAGES, SETTINGS, SKILLS, LANGUAGE_PACKS, _PLUGIN_META = {}, {}, {}, [], {}, {}
    disabled = set(disabled or [])
    # 显式启用的白名单(用于"默认关闭"插件)
    enabled_list = (settings or {}).get("plugins_enabled", []) or []
    enabled_set = set(enabled_list) if enabled_list else set()
    loaded = {}
    for name, path in discover_plugins():
        # 判断是否装载:显式禁用 → 否;默认关且未显式启用 → 否;否则装
        if name in disabled:
            loaded[name] = False
            continue
        mod = _load_plugin_module(path)
        default_on = True
        if mod is not None:
            default_on = bool(getattr(mod, "PLUGIN_DEFAULT_ENABLED", True))
        if not default_on and name not in enabled_set:
            loaded[name] = False
            continue
        loaded[name] = load_plugin(name, path, disabled)
    return loaded


def settings_has(settings: dict, key: str) -> bool:
    return bool(settings.get(key))
