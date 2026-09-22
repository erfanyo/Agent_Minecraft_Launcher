# -*- coding: utf-8 -*-
"""
插件系统(骨架):让启动器的功能以「插件」形式存在,并让 AI 能扩展。

设计目标(来自「一切皆插件」):
1. 现有**非核心/可选功能**可作为插件注册、卸载(设置→插件 列出来,可启禁);
   核心组件(启动/实例/下载/设置/AI)不插件化,保持稳定。
2. 插件 = `plugins/<名字>.py`,提供 `register(api)` 函数,在启动时被扫描装载(静态加载)。
   注册点:AI 工具 / 主标签页 / **实例详情分区** / 设置页 / 中心页 / 技能(Skill) / 语言包。
3. 插件启停状态存设置 `settings["plugins_disabled"]`(默认全开);禁用则不装载其注册内容。

设计原则:
- **对既有代码零侵入**:插件通过 api 回调把「注册内容」登记进全局 registry,
  由既有消费方(工具/页面/设置/技能)在需要时读取;不改造原有内部逻辑。
- **安全**:插件是本地代码,信任模型和 AI 工具/技能类似(本地可信)。未来可加
  权限/沙箱(复用 ai_actions),当前先记录。

**许可证约定(独立作品 vs 派生作品)**:
- 启动器本体 = GPL-3.0-only;作者自研插件默认也随启动器采用 GPL-3.0-only。
- 第三方插件可以声明自己的许可；是否构成启动器的派生作品，应按代码来源和实际结合方式判断，
  不能只凭“插件”名称或通过公开 API 注册就一概认定。
- 若插件修改/派生启动器核心(改内部实现/共享深层),则须遵守 GPL-3.0-only。建议守住分界线:
  插件只依赖 `api` 与 PySide6,不 import 启动器内部模块改行为、不 monkeypatch 核心类。


plugin_api: 每个插件注册时收到的 api 对象,见下方 build_api();它把各注册点的
「登记函数」暴露给插件,插件调用后写入全局 registry。
"""
import importlib.util
import os

# 对外插件契约从 1 开始独立版本化。启动器内部可以继续演进，插件只需面对这里
# 明确列出的接口；不再靠“能 import 到什么就用什么”。
PLUGIN_API_VERSION = 1

# plugins 目录(启动器私有数据,不进 git;模板/示例可放仓库根 plugins_templates)
PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")

# ---------------- 全局注册表(插件登记的内容) ----------------
# 各注册点 = {} 或 [],由消费方读取;插件 register() 时写入。
TOOLS = {}            # name -> (描述, 参数schema, 处理函数)  (AI 工具)
TOOL_POLICIES = {}    # name -> {write, confirm}，由统一执行器处理权限和确认
SKILLS = []           # [Skill子类]                            (技能)
LANGUAGE_PACKS = {}   # pack_id -> {"name", "pack"}            (语言包:文本覆盖)
MAIN_TABS = []        # [(label, build_fn)]                    (主标签页,与 下载新资源/联机/设置 平级)
# [(plugin_id, label, watch_mods, build_fn)]                   (实例详情分区)
# 为什么不让插件各自开一个主标签页:「皮肤/枪包/原理图」这类页只在**某个实例**里
# 才有意义,做成顶部标签既要在页内再放实例下拉框,又会把顶部标签栏撑满。放进实例
# 详情的左侧菜单,和「Mod / 光影包 / 数据包」同级,才是它该在的位置。
INSTANCE_SECTIONS = []

# 最近一次装载的可读报告。过去插件异常会被静默吞掉，开发者只能猜“为什么没出现”。
LOAD_REPORTS = {}     # plugin_id -> {"state": loaded/skipped/error, "message": str}
CENTER_PAGES = {}     # center -> [(plugin_id, page_id, label, builder)]

# ---- 插件元数据(从插件模块读取):默认启禁 / 独立设置页 ----
# discover_plugins 返回 [(name, path, meta)];meta 含 default_enabled / has_settings / settings_page
_PLUGIN_META = {}     # name -> {default_enabled(bool), settings_build_fn(callable|None), name, description}


class PluginAPI:
    """插件注册时拿到的 api,提供各注册点的登记函数。

    v2(软沙箱)新增:
    - data_dir():返回该插件【专属数据目录】(AMCL/plugins_data/<插件id>/),自动创建。
      插件应该只读写这个目录,别写系统路径/安装目录外。启动器清理/迁移只动 plugins_data。
    - data_path(name):该插件专属目录下某文件/子路径(等价 data_dir()/<name>)。
    - 沙箱是"约定 + 受限 api"软约束(不硬做进程隔离;真沙箱观望 Win 容器化)。
    """

    def __init__(self, plugin_id: str, settings: dict | None = None):
        self.plugin_id = plugin_id
        self._settings = settings if settings is not None else {}

    # ---- 软沙箱:数据目录收口 ----
    def data_dir(self) -> str:
        """本插件专属数据目录(AMCL/plugins_data/<插件id>),自动创建。"""
        import paths
        return paths.data_dir(os.path.join("plugins_data", self.plugin_id))

    def data_path(self, name: str) -> str:
        """本插件专属目录下某文件/子路径。name 需为相对路径。"""
        d = self.data_dir()
        rel = (name or "").replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
        candidate = os.path.abspath(os.path.join(d, rel))
        if os.path.commonpath((os.path.abspath(d), candidate)) != os.path.abspath(d):
            raise ValueError("data_path 只能指向插件自己的数据目录")
        return candidate

    def get_config(self, key: str, default=None):
        """读取本插件自己的持久化配置。配置键会自动加插件 id 前缀。"""
        return self._settings.get(f"plugin.{self.plugin_id}.{key}", default)

    def set_config(self, key: str, value) -> None:
        """保存本插件自己的持久化配置；不允许直接改启动器核心设置。"""
        full_key = f"plugin.{self.plugin_id}.{key}"
        self._settings[full_key] = value
        from settings import update_setting
        update_setting(full_key, value)

    def register_tool(self, name, description, parameters, handler,
                      write: bool = False, confirm: bool = False):
        """AI 工具。name 会加前缀 <插件id>__ 防冲突。handler(args_dict)->str。"""
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            raise ValueError("AI 工具名只能包含字母、数字和下划线")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("AI 工具必须提供说明")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError("AI 工具 parameters 必须是 type=object 的 JSON Schema")
        if not callable(handler):
            raise TypeError("AI 工具 handler 必须可调用")
        full = f"{self.plugin_id}__{name}"
        if full in TOOLS:
            raise ValueError(f"AI 工具重名:{full}")
        TOOLS[full] = (description, parameters, handler)
        TOOL_POLICIES[full] = {"write": bool(write), "confirm": bool(confirm)}

    def register_skill(self, skill_cls):
        """技能(Skill 子类,与 skill_manager.BUILTIN_SKILLS 同款接口)。"""
        SKILLS.append(skill_cls)

    def bind_ai_context(self, widget, context_id: str, name: str, description: str, provider=None):
        """Expose an explicit read-only pin snapshot on a plugin widget (GUI thread).

        Optional provider() returns a string describing current state. Never perform
        network requests, writes or actions here. Binding does not register tools.
        """
        from PySide6.QtWidgets import QWidget
        if not isinstance(widget, QWidget):
            raise TypeError("图钉目标必须是 QWidget")
        if not all(isinstance(value, str) and value.strip() for value in (context_id, name, description)):
            raise ValueError("图钉需要非空的 ID、名称和说明")
        if provider is not None and not callable(provider):
            raise TypeError("provider 必须可调用")
        plugin_id = self.plugin_id
        def snapshot(pos):
            content = provider() if provider is not None else ""
            if not isinstance(content, str):
                raise TypeError("图钉 provider 必须返回字符串")
            return {"id": f"plugin:{plugin_id}:{context_id}", "kind": "plugin",
                    "plugin_id": plugin_id, "name": name, "description": description,
                    "content": content}
        widget.ai_pin_provider = snapshot

    def exclude_ai_context(self, widget):
        """Disallow pin capture for a sensitive widget and all of its children."""
        widget.setProperty("ai_pin_sensitive", True)

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
        if not isinstance(label, str) or not label.strip() or not callable(build_fn):
            raise ValueError("主标签页需要非空标题和可调用的 build_fn")
        if any(old_label == label for old_label, _ in MAIN_TABS):
            raise ValueError(f"主标签页重名:{label}")
        MAIN_TABS.append((label, build_fn))

    def register_instance_section(self, label: str, build_fn, *, watch_mods=()):
        """注册一个【实例详情分区】:出现在实例详情左侧菜单里(和 Mod/光影包 同级)。

        ``build_fn(ctx)`` 收到一个 :class:`InstanceSectionContext`,里面有实例目录、
        游戏目录、``ctx.has_mod(...)`` 与 ``ctx.open_dir(...)``;它返回 QWidget。
        插件不该去够启动器内部对象,所以这里只给这个明确的小接口。

        ``watch_mods`` = mod 关键字;只有当实例真的装了其中之一时,这个分区才会
        出现(与模块级 ``WATCH_MODS`` 同口径,通常直接传它)。留空则总是出现。
        """
        if not isinstance(label, str) or not label.strip() or not callable(build_fn):
            raise ValueError("实例详情分区需要非空标题和可调用的 build_fn")
        keys = watch_mods
        if isinstance(keys, str):
            keys = (keys,)
        keys = tuple(str(k).strip() for k in (keys or ()) if str(k).strip())
        if any(old_label == label for _, old_label, _, _ in INSTANCE_SECTIONS):
            raise ValueError(f"实例详情分区重名:{label}")
        INSTANCE_SECTIONS.append((self.plugin_id, label, keys, build_fn))

    def register_center_page(self, center: str, page_id: str, label: str, build_fn):
        """Register a lazy sidebar page. Currently supported center: online."""
        if center != 'online':
            raise ValueError('当前支持的中心为 online')
        if not all(isinstance(s, str) and s.strip() for s in (page_id, label)) or not callable(build_fn):
            raise ValueError('页面需要 ID、标题和构建函数')
        pages = CENTER_PAGES.setdefault(center, [])
        if any((pid == self.plugin_id and key == page_id) or title == label
               for pid, key, title, _ in pages):
            raise ValueError('插件页面 ID 或标题重复')
        pages.append((self.plugin_id, page_id, label, build_fn))

    def open_web_window(self, title: str, html: str, *, handlers=None,
                        width=1100, height=760, on_error=None):
        """GUI-thread only. Trusted inline HTML; explicit JSON RPC handlers only.

        Returns a handle with close(). Keep handlers short (they run on GUI thread).
        Requires optional pywebview; Windows uses shared WebView2, never QtWebEngine.
        """
        from plugin_web_window import open_web_window
        return open_web_window(title, html, handlers=handlers, width=width,
                               height=height, on_error=on_error)


def build_api(plugin_id: str, settings: dict | None = None) -> PluginAPI:
    return PluginAPI(plugin_id, settings)


class InstanceSectionContext:
    """插件实例分区的只读上下文(插件能看到的全部实例信息)。

    刻意做得很小:插件只需要知道「是哪个实例、目录在哪、装没装某个 mod」,
    不需要(也不该)拿到 InstanceManagerDialog 的内部。
    """

    def __init__(self, instance_id: str, instance_dir: str, game_dir: str,
                 has_mod=None, open_dir=None, status=None):
        self.instance_id = instance_id
        self.instance_dir = instance_dir
        self.game_dir = game_dir
        self._has_mod = has_mod
        self._open_dir = open_dir
        self._status = status

    def has_mod(self, *keys) -> bool:
        """实例的 mods 目录里是否有文件名含任一关键字(与核心同口径)。"""
        if self._has_mod is None:
            return False
        return bool(self._has_mod(*keys))

    def open_dir(self, path: str):
        """在系统文件管理器里打开目录(不存在则创建)。"""
        if self._open_dir is not None:
            self._open_dir(path)

    def status(self, text: str):
        """在启动器状态栏显示一句话(可选)。"""
        if self._status is not None:
            self._status(text)


def instance_sections_for(has_mod) -> list:
    """当前该显示的实例分区 → ``[(label, build_fn, plugin_id)]``,保持注册顺序。

    ``has_mod`` = ``callable(*keys) -> bool``,由调用方按具体实例判断。
    """
    out = []
    for plugin_id, label, watch_mods, build_fn in list(INSTANCE_SECTIONS):
        if watch_mods and not has_mod(*watch_mods):
            continue
        out.append((label, build_fn, plugin_id))
    return out


def _read_plugin_meta(mod) -> dict:
    """从插件模块读元数据:名称、默认启停、API 版本和签名溯源。"""
    try:
        default_enabled = bool(getattr(mod, "PLUGIN_DEFAULT_ENABLED", True))
    except Exception:
        default_enabled = True
    meta = {
        "name": getattr(mod, "PLUGIN_NAME", None),
        "description": getattr(mod, "PLUGIN_DESCRIPTION", ""),
        "api_version": getattr(mod, "PLUGIN_API_VERSION", 0),
        # 注意:register() 里的 register_settings_page 会写入 _PLUGIN_META[name]["settings_build_fn"]
        "default_enabled": default_enabled,
        # 签名溯源:默认 unknown;验签通过=official,无签名/验签失败=ai_generated/unknown
        "trust": "unknown", "author": "",
    }
    # ---- 签名溯源(ed25519;见 plugin_sign.py)----
    try:
        import inspect, plugin_sign
        sig = getattr(mod, "PLUGIN_SIGNATURE", None)
        if sig:
            src = inspect.getsource(mod)
            ok, author = plugin_sign.verify_plugin(src, sig)
            if ok:
                meta["trust"] = "official"
                meta["author"] = author
            elif plugin_sign.is_crypto_available():
                # cryptography 在但验签失败 → 签名无效(可能被改/非作者)
                meta["trust"] = "signed_invalid"
                meta["author"] = author or ""
            else:
                meta["trust"] = "unsigned"   # 无 cryptography → 无法验签
        else:
            # 无签名:本地/AI 生成
            meta["trust"] = "unsigned"
    except Exception:
        meta["trust"] = "unsigned"
    return meta


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
    import ast
    meta_out = {}
    for name, path in discover_plugins():
        base = {"default_enabled": True, "name": name, "description": "", "version": "",
                "api_version": 0, "has_settings": False, "trust": "unsigned", "author": ""}
        try:
            with open(path, encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=path)
            constants = {}
            for node in tree.body:
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)):
                    continue
                key = node.targets[0].id
                if key.startswith("PLUGIN_"):
                    try:
                        constants[key] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
            m = dict(base)
            m.update({
                "name": constants.get("PLUGIN_NAME") or name,
                "description": str(constants.get("PLUGIN_DESCRIPTION") or ""),
                "version": str(constants.get("PLUGIN_VERSION") or ""),
                "api_version": constants.get("PLUGIN_API_VERSION", 0),
                "default_enabled": bool(constants.get("PLUGIN_DEFAULT_ENABLED", True)),
                "author": str(constants.get("PLUGIN_AUTHOR") or ""),
            })
            m["has_settings"] = any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "register_settings_page"
                for node in ast.walk(tree)
            )
            signature = constants.get("PLUGIN_SIGNATURE")
            if signature:
                try:
                    import plugin_sign
                    ok, author = plugin_sign.verify_plugin(source, signature)
                    m["trust"] = "official" if ok else (
                        "signed_invalid" if plugin_sign.is_crypto_available() else "unsigned")
                    m["author"] = author or m["author"]
                except Exception:
                    m["trust"] = "unsigned"
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
    enabled = set(settings.get("plugins_enabled", []) or [])
    meta = discover_plugins_meta().get(name, {})
    return not bool(meta.get("default_enabled", True)) and name not in enabled


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
    """校验 AI 生成的插件代码:语法、API 版本和 register(api) 入口。
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
    declared_version = None
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "PLUGIN_API_VERSION"):
            try:
                declared_version = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
            break
    if declared_version != PLUGIN_API_VERSION:
        return False, {"error": f"需要声明 PLUGIN_API_VERSION = {PLUGIN_API_VERSION}"}
    return True, {"name": None}


# ---------------- 危险 import / 调用审计(安装时告诉安装者它 import/调用什么) ----------------
# 不静默拒绝,而是"公开 + 标注",由安装者判断信任。
_DANGEROUS_IMPORTS = {
    "os": "文件系统操作(os.system/os.popen 等)",
    "subprocess": "启动子进程",
    "socket": "网络 socket",
    "requests": "HTTP 请求(网络)",
    "urllib": "网络请求",
    "ctypes": "系统底层调用",
    "winreg": "Windows 注册表",
    "shutil": "文件/目录操作(复制/删除/移动)",
    "pickle": "反序列化(可能执行恶意 payload)",
    "importlib": "动态导入(潜在混淆/反编译规避)",
}
_DANGEROUS_CALLS = {
    "os.system": "执行 shell 命令",
    "os.popen": "执行 shell 命令",
    "eval": "动态执行代码",
    "exec": "动态执行代码",
    "open": "写/读文件(需检查路径)",
}


def audit_plugin_code(code: str) -> dict:
    """静态审计(AST)插件代码,返回:
    {"imports": ["os", "requests", ...], "danger_calls": ["os.system", ...],
     "dangers": str 列表(给人看的中文描述), "ok": bool(是否无可疑项)}
    未执行代码。"""
    import ast
    out = {"imports": [], "danger_calls": [], "dangers": [], "ok": True}
    if not code or not code.strip():
        return out
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return out
    # 收集 import
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mod = a.name.split(".")[0]
                if mod in _DANGEROUS_IMPORTS and mod not in out["imports"]:
                    out["imports"].append(mod)
        elif isinstance(n, ast.ImportFrom):
            mod = (n.module or "").split(".")[0]
            if mod in _DANGEROUS_IMPORTS and mod not in out["imports"]:
                out["imports"].append(mod)
        # 危险调用(os.system / eval / exec ...)
        if isinstance(n, ast.Call):
            fn = n.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = f"{__attr_base(fn.value)}.{fn.attr}"
            if name in _DANGEROUS_CALLS:
                if name not in out["danger_calls"]:
                    out["danger_calls"].append(name)
    # 组装给人看的中文描述
    for m in out["imports"]:
        out["dangers"].append(f"import {m} —— {_DANGEROUS_IMPORTS[m]}")
    for c in out["danger_calls"]:
        out["dangers"].append(f"调用 {c} —— {_DANGEROUS_CALLS[c]}")
    out["ok"] = not (out["imports"] or out["danger_calls"])
    return out


def __attr_base(node) -> str:
    """把 Attribute/value 简化成字符串基名(如 a.b.c → a)。"""
    import ast
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)) if parts else ""


def save_plugin(name: str, code: str) -> dict:
    """把 AI 生成的插件代码落盘到 plugins/<name>.py。
    - 校验语法 + register 存在;
    - 文件名安全化(name 只留字母数字下划线);
    - 静态审计危险 import/调用(附到返回,供安装者判断);
    - 写文件,返回 {ok, path, name, restart_needed:True, audit}。"""
    import re
    safe = re.sub(r"[^A-Za-z0-9_]", "_", (name or "").strip()) or "plugin"
    ok, info = validate_plugin_code(code)
    if not ok:
        return {"ok": False, "error": info.get("error", "校验失败")}
    audit = audit_plugin_code(code)
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    path = os.path.join(PLUGIN_DIR, safe + ".py")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
    except Exception as e:
        return {"ok": False, "error": f"写入失败:{type(e).__name__}: {e}"}
    return {"ok": True, "path": path, "name": safe, "restart_needed": True, "audit": audit}


# ---------------- 插件商店(仓库注册 / 远程插件清单 / 安装) ----------------
# 仓库清单格式(仓库根 plugins.json,或某仓库 URL 直接返回 JSON):
#   [ {"name": "lan_bridge", "version": "0.1.0", "title": "联机 CLI 桥接",
#      "description": "…", "download_url": "https://…/lan_bridge.py",
#      "repo": "官方", "author": "…"}, ... ]
# 安装 = 下载 download_url 的单文件 .py → 校验 → 落盘 plugins/<name>.py(复用 save_plugin)。

def _resolve_registry_url(url: str) -> str:
    """把仓库源 URL 规范成「能直接作为 JSON 清单请求」的地址。

    支持:
    - GitHub 仓库主页 / git 地址(https://github.com/user/repo 或 …/.git)
      → 转成 https://raw.githubusercontent.com/user/repo/<branch>/plugins.json
      (默认分支 main;若 raw 404 可再回退 master —— 见 load_registry);
    - 已经是 raw.githubusercontent.com / 其它 http(s) 直链 / file://  → 原样返回。
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return url
    # file:// 或已是 raw 直链 → 不动
    if url.startswith("file://") or "raw.githubusercontent.com" in url:
        return url
    # GitHub 主页 / git 地址 → 转 raw 直链
    import re as _re
    m = _re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if m:
        user, repo = m.group(1), m.group(2)
        return f"https://raw.githubusercontent.com/{user}/{repo}/main/plugins.json"
    # 其它:原样(可能直接就是可返回 JSON 的 URL,如 raw.githubusercontent.com / 自建 API)
    return url


def load_registry(url: str) -> list:
    """从插件仓库源拉取插件清单,返回 [{name, version, title, description, download_url, repo}]。
    支持:http(s) URL(GitHub raw 等)返回清单,或本地 file://(调试/测试)。失败返回 []。"""
    url = _resolve_registry_url(url)
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
        # GitHub 仓库默认分支可能不是 main(是 master)——转一次再试
        if "raw.githubusercontent.com" in url and "/main/" in url:
            try:
                import requests
                alt = url.replace("/main/", "/master/")
                r = requests.get(alt, timeout=12)
                r.raise_for_status()
                data = r.json()
                rows = data if isinstance(data, list) else data.get("plugins", [])
            except Exception:
                return []
        else:
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


def load_plugin(name: str, path: str, disabled: set, settings: dict | None = None) -> bool:
    """装载一个插件:调用其 register(api) 登记内容。
    disabled:插件 id 集合(被禁用则跳过)。返回是否装载成功。"""
    if name in disabled:
        LOAD_REPORTS[name] = {"state": "skipped", "message": "已禁用"}
        return False
    try:
        mod = _load_plugin_module(path)
    except Exception as e:
        LOAD_REPORTS[name] = {"state": "error", "message": f"导入失败:{type(e).__name__}: {e}"}
        return False
    if mod is None or not hasattr(mod, "register"):
        LOAD_REPORTS[name] = {"state": "error", "message": "缺少 register(api) 入口"}
        return False
    api_version = getattr(mod, "PLUGIN_API_VERSION", 0)
    if api_version != PLUGIN_API_VERSION:
        LOAD_REPORTS[name] = {
            "state": "error",
            "message": f"插件 API 版本不兼容:需要 {PLUGIN_API_VERSION}，插件声明 {api_version or '未声明'}",
        }
        return False
    try:
        mod.register(build_api(name, settings))
        LOAD_REPORTS[name] = {"state": "loaded", "message": "已加载"}
        return True
    except Exception as e:
        LOAD_REPORTS[name] = {"state": "error", "message": f"注册失败:{type(e).__name__}: {e}"}
        for center, pages in CENTER_PAGES.items():
            CENTER_PAGES[center] = [row for row in pages if row[0] != name]
        # 注册到一半失败的插件,已登记的分区也要撤掉,避免留下半成品页
        INSTANCE_SECTIONS[:] = [row for row in INSTANCE_SECTIONS if row[0] != name]
        return False


def load_all(settings: dict | None = None, disabled: set | None = None) -> dict:
    """启动时装载所有插件。disabled = 被禁用的插件 id 集合(显式禁用)。
    额外考虑"默认关闭"插件:PLUGIN_DEFAULT_ENABLED=False 且未被显式启用(settings['plugins_enabled'])
    的插件不装载。返回 {插件名: bool(是否装载)}。清空全局注册表后再扫。"""
    global TOOLS, TOOL_POLICIES, SKILLS, LANGUAGE_PACKS, MAIN_TABS, _PLUGIN_META, LOAD_REPORTS, CENTER_PAGES, INSTANCE_SECTIONS
    CENTER_PAGES = {}
    TOOLS, TOOL_POLICIES, SKILLS, LANGUAGE_PACKS, MAIN_TABS, _PLUGIN_META = {}, {}, [], {}, [], {}
    INSTANCE_SECTIONS = []
    LOAD_REPORTS = {}
    # 禁用集合 = 显式传入 disabled 并上 settings["plugins_disabled"](传 settings 时生效)
    disabled = set(disabled or [])
    disabled |= set((settings or {}).get("plugins_disabled", []) or [])
    # 显式启用的白名单(用于"默认关闭"插件)
    enabled_list = (settings or {}).get("plugins_enabled", []) or []
    enabled_set = set(enabled_list) if enabled_list else set()
    loaded = {}
    for name, path in discover_plugins():
        # 判断是否装载:显式禁用 → 否;默认关且未显式启用 → 否;否则装
        if name in disabled:
            loaded[name] = False
            LOAD_REPORTS[name] = {"state": "skipped", "message": "已禁用"}
            continue
        try:
            mod = _load_plugin_module(path)
            default_on = bool(getattr(mod, "PLUGIN_DEFAULT_ENABLED", True)) if mod is not None else True
        except Exception as e:
            loaded[name] = False
            LOAD_REPORTS[name] = {"state": "error", "message": f"读取元数据失败:{type(e).__name__}: {e}"}
            continue
        if not default_on and name not in enabled_set:
            loaded[name] = False
            LOAD_REPORTS[name] = {"state": "skipped", "message": "默认关闭，尚未启用"}
            continue
        loaded[name] = load_plugin(name, path, disabled, settings)
    return loaded


def settings_has(settings: dict, key: str) -> bool:
    return bool(settings.get(key))
