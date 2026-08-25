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
MAIN_TABS = []        # [(label, build_fn)]                    (主标签页,与 下载新资源/联机/设置 平级)

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

    def register_main_tab(self, label: str, build_fn):
        """注册一个【主标签页】(与 下载新资源/联机/设置 平级)。build_fn() 返回 QWidget。
        MainWindow 构建时会把启用的插件标签页 addTab 到主标签栏。"""
        MAIN_TABS.append((label, build_fn))


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
                     _pm.LANGUAGE_PACKS, _pm.MAIN_TABS, _pm._PLUGIN_META)
            try:
                _pm.TOOLS, _pm.GUI_PAGES, _pm.SETTINGS = {}, {}, {}
                _pm.SKILLS, _pm.LANGUAGE_PACKS, _pm.MAIN_TABS, _pm._PLUGIN_META = [], {}, [], {}
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
                 _pm.LANGUAGE_PACKS, _pm.MAIN_TABS, _pm._PLUGIN_META) = saved
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


def validate_plugin_code(code: str) -> tuple:
    """校验 AI 生成的插件代码:语法是否正确 + 是否含 register(api)。
    返回 (ok, {error 或 name})。仅静态检查(AST),不执行。"""
    import ast
    if not code or not code.strip():
        return False, {"error": "代码为空"}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, {"error": f"语法错误:{e.msg}(第 {e.lineno} 行)"}
    has_register = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "register"
                       for n in ast.walk(tree))
    if not has_register:
        return False, {"error": "缺少 register(api) 函数(插件入口)"}
    return True, {"name": None}


def save_plugin(name: str, code: str) -> dict:
    """把 AI 生成的插件代码落盘到 plugins/<name>.py。
    - 校验语法 + register 存在;
    - 文件名安全化(name 只留字母数字下划线);
    - 写文件,返回 {ok, path, name, restart_needed:True}。"""
    import re
    safe = re.sub(r"[^A-Za-z0-9_]", "_", (name or "").strip()) or "plugin"
    ok, info = validate_plugin_code(code)
    if not ok:
        return {"ok": False, "error": info.get("error", "校验失败")}
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    path = os.path.join(PLUGIN_DIR, safe + ".py")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return {"ok": False, "error": f"写入失败:{type(e).__name__}: {e}"}
    return {"ok": True, "path": path, "name": safe, "restart_needed": True}


# ---------------- 插件商店(仓库注册 / 远程插件清单 / 安装) ----------------
# 仓库清单格式(仓库根 plugins.json,或某仓库 URL 直接返回 JSON):
#   [ {"name": "lan_bridge", "version": "0.1.0", "title": "联机 CLI 桥接",
#      "description": "…", "download_url": "https://…/lan_bridge.py",
#      "repo": "官方", "author": "…"}, ... ]
# 安装 = 下载 download_url 的单文件 .py → 校验 → 落盘 plugins/<name>.py(复用 save_plugin)。

def load_registry(url: str) -> list:
    """从插件仓库源拉取插件清单,返回 [{name, version, title, description, download_url, repo}]。
    支持:http(s) URL(GitHub raw 等)返回清单,或本地 file://(调试/测试)。失败返回 []。"""
    try:
        if url.startswith("file://"):
            from urllib.parse import unquote
            p = unquote(url[len("file://"):])
            if p.startswith("/") and ":" in p:   # Windows: file:///C:/... -> C:/...
                p = p.lstrip("/")
            with open(p, encoding="utf-8") as f:
                import json as _json
                data = _json.load(f)
        else:
            import requests
            r = requests.get(url, timeout=12)
            r.raise_for_status()
            data = r.json()
        rows = data if isinstance(data, list) else data.get("plugins", [])
    except Exception:
        return []
    out = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "title": it.get("title") or it.get("name") or name,
            "version": it.get("version", ""),
            "description": it.get("description", ""),
            "download_url": it.get("download_url", it.get("url", "")),
            "repo": it.get("repo", url),
            "author": it.get("author", ""),
        })
    return out


def list_remote_plugins(registries: list) -> dict:
    """拉取多个仓库源的插件清单,按 name 去重(后加的覆盖)。返回 {name: entry}。"""
    merged = {}
    for r in registries or []:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        for e in load_registry(url):
            merged[e["name"]] = e   # 后注册的仓库覆盖同名
    return merged


def install_remote_plugin(entry: dict) -> dict:
    """从仓库安装一个插件:下载单文件 → 校验 → 落盘 plugins/<name>.py。
    返回 {ok, name, path} 或 {ok:False, error}。"""
    name = (entry.get("name") or "").strip()
    dl = (entry.get("download_url") or "").strip()
    if not name or not dl:
        return {"ok": False, "error": "插件缺少 name 或 download_url"}
    try:
        if dl.startswith("file://"):
            from urllib.parse import unquote
            p = unquote(dl[len("file://"):])
            if p.startswith("/") and ":" in p:
                p = p.lstrip("/")
            with open(p, encoding="utf-8") as f:
                code = f.read()
        else:
            import requests
            r = requests.get(dl, timeout=30)
            r.raise_for_status()
            code = r.text
    except Exception as e:
        return {"ok": False, "error": f"下载失败:{type(e).__name__}: {e}"}
    return save_plugin(name, code)


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
    global TOOLS, GUI_PAGES, SETTINGS, SKILLS, LANGUAGE_PACKS, MAIN_TABS, _PLUGIN_META
    TOOLS, GUI_PAGES, SETTINGS, SKILLS, LANGUAGE_PACKS, MAIN_TABS, _PLUGIN_META = {}, {}, {}, [], {}, [], {}
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
