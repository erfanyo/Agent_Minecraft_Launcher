# plugin_manager 插件开发 API 文档

> 面向**人类开发者**如何手写启动器插件。插件 = `plugins/<名字>.py`，提供 `register(api)`，启动时静态装载。
> 本文是 **Plugin API v1** 的唯一公开契约；未列出的启动器模块都属于内部实现，不能依赖。
> 安全：插件是本地代码，但**可能来自 AI 生成或第三方**（不可信），见 §6 安全约束 & §7 信任分级。

---

## 1. 最小插件

```python
PLUGIN_API_VERSION = 1           # 必填；必须等于启动器要求的版本
PLUGIN_ID = "my_plugin"          # 插件唯一 id(用作工具名/配置前缀)
PLUGIN_NAME = "我的插件"         # 显示名(设置→插件 列表)
PLUGIN_DESCRIPTION = "一句话说明这个插件干嘛"
PLUGIN_DEFAULT_ENABLED = True    # 可选:False=默认关闭(按需启用,如 MCP 服务器)

def register(api):
    # 在这里调用 api.register_* 注册你的内容
    pass
```

**生命周期**：`register(api)` 在启动器启动时被调用一次；**改动插件需重启启动器生效**（静态加载，无热重载）。

---

## 2. `api` 对象（`PluginAPI`）

`register(api)` 收到的 api 是 `plugin_manager.PluginAPI`，提供全部注册函数。

| 方法 | 说明 | 返回/副作用 |
|---|---|---|
| `register_tool(name, description, parameters, handler)` | 注册 AI 工具。实际工具名为 `<插件id>__<name>` | 写全局 `TOOLS` |
| `register_main_tab(label, build_fn)` | 注册主标签页(与 下载新资源/设置 平级) | 写 `MAIN_TABS` |
| `register_instance_section(label, build_fn, watch_mods=())` | 注册**实例详情分区**(与 Mod/光影包 同级;装了 watch_mods 里的 mod 才出现) | 写 `INSTANCE_SECTIONS` |
| `register_settings_page(build_fn)` | 注册独立设置页(左菜单单开一行) | 写 `_PLUGIN_META` |
| `register_skill(skill_cls)` | 注册技能(Skill 子类) | 追加 `SKILLS` |
| `register_language_pack(pack_id, name, pack, lang="")` | 注册语言包(文本覆盖) | 写 `LANGUAGE_PACKS` |
| `get_config(key, default=None)` / `set_config(key, value)` | 读取或保存插件私有配置 | 自动使用 `plugin.<插件id>.*` 命名空间 |

### 2.1 `register_tool`

### 2.1.1 `register_instance_section`(mod 专属页面走这条)

「皮肤/枪包/原理图」这类**只在某个实例里有意义**的页面不要注册主标签页,注册成
实例详情分区:它出现在实例详情的左菜单里(和 Mod/光影包同级),顶部标签栏不会被撑满。

```python
PLUGIN_DEFAULT_ENABLED = False          # 默认关闭,靠「检测到 mod」再问用户
WATCH_MODS = ("tacz", "timeless_and_classics")

def register(api):
    def build(ctx):
        # ctx: instance_id / instance_dir / game_dir / has_mod(*keys) / open_dir() / status()
        return PackFolderPanel(os.path.join(ctx.instance_dir, "tacz", "gunpack"),
                               hint="枪包放进 tacz/gunpack…", on_status=ctx.status)
    api.register_instance_section("枪包(TACZ)", build, watch_mods=WATCH_MODS)
```

要点:

- `build_fn(ctx)` 返回 `QWidget`;`ctx` 只给实例标识、目录和目录操作,**不要**去够启动器内部对象;
- `watch_mods` 留空 = 分区总是出现;填了 = 只在实例真装了对应 mod 时出现;
- 声明 `WATCH_MODS` + `PLUGIN_DEFAULT_ENABLED = False`,装了该 mod 的用户启动时会收到
  **一次**「要不要启用这个插件」的提示(拒绝后不再问);
- 核心已有通用面板 `pack_folder_ui.PackFolderPanel`(列目录/导入/删除/拖放),
  目录是 mod 自己生成的就传 `read_only=True`。**动手前先看真实目录**,别把
  mod 生成的数据目录当成「丢文件进去」的目录。
### 图钉上下文（API v1 的兼容扩展）

`api.bind_ai_context(widget, context_id, name, description, provider=None)`
让用户从 AI Dock 拖图钉到插件控件上，固定插件说明与当前状态。
ID 在插件内部应稳定且唯一；启动器自动加插件命名空间。

```python
api.bind_ai_context(
    panel, "connection_status", "联机状态",
    "展示本插件的连接状态，不代表用户授权连接或断开。",
    provider=lambda: "当前状态：" + status_label.text(),
)
api.exclude_ai_context(secret_panel)  # 包括子控件，禁止固定敏感内容
```

`provider()` 在用户放下图钉时于 GUI 线程调用，必须快速返回字符串；
不要联网、读大文件、修改状态或执行操作。省略时仅发送名称和说明。
不要返回密钥、密码、访问令牌或不相关的私人内容。
启动器会对快照脱敏并截断，用户发消息时才发送给所选模型。
固定之后的内容不会随页面变化；重新固定同 ID 可更新快照。
不需要导入启动器内部模块，不会注册工具，也不改变原有工具权限。
这不是 Python 沙箱，无法隔离第三方插件代码本身。

普通文字标签和按钮支持文字固定；输入框不自动捕获。
控件绑定的插件描述优先于其子控件的普通文字；敏感标记优先级最高。

### `register_tool` 示例
```python
def register(api):
    def my_action(args: dict) -> str:
        # args = AI 传的参数 dict;返回 str(文本回给 AI)
        return f"处理了 {args.get('x')}"
    api.register_tool(
        name="do_thing",                 # → 实际 my_plugin__do_thing
        description="给 AI 看:何时调用、干嘛用",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string", "description": "参数说明"}},
            "required": ["x"],
        },
        handler=my_action,
    )
```

### 2.2 `register_main_tab` / `register_settings_page`
两者 `build_fn()` 都返回一个 `QWidget`；`register_main_tab` 与 下载新资源/联机/设置 平级，`register_settings_page` 在设置左菜单单开一行。
不要再用“注册一个嵌进插件管理页的普通页面”这类模糊入口：需要常用入口就注册主标签页，需要配置就注册设置页，
**只在某个实例里才有意义的页面**（皮肤/枪包/原理图这类 mod 专属目录）注册实例详情分区（见 2.1.1）。

### 2.3 `register_skill`
```python
from skill_manager import Skill
class MySkill(Skill):
    id = "my_plugin_skill"; name = "我的技能"; description = "..."
    category = "运行辅助"; default_enabled = True
    def ai_hint(self) -> str:  # 注入 AI 系统提示
        return "【我的技能】启用后 AI 要……"
    # 可选生命周期钩子:on_game_start(process, instance_id) / on_game_log(line) / on_game_stop(exit_code)
api.register_skill(MySkill)
```

---

## 3. 元数据字段（模块级）

在插件文件顶层声明，`plugin_manager` 读取：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `PLUGIN_API_VERSION` | int | ✅ | 当前必须为 `1`；版本不匹配时插件不会加载 |
| `PLUGIN_ID` | str | ✅ | 插件唯一 id（作为工具/配置前缀）|
| `PLUGIN_NAME` | str | ✅ | 显示名 |
| `PLUGIN_DESCRIPTION` | str | 否 | 描述 |
| `PLUGIN_DEFAULT_ENABLED` | bool | 否 | 默认启用（缺省 True）|

---

## 4. 数据目录约定

插件**自身的状态/缓存**放启动器私有的 `AMCL/` 下的一个子目录（**不要写系统路径、不要写安装目录外的任意位置**）。

```python
def register(api):
    data_dir = api.data_dir()   # 返回 AMCL/plugins_data/<插件id>/ (自动创建)
    # 把你的缓存/状态写到这里;启动器迁移/清理时只清这个目录,不碰用户数据
```

`api.data_path()` 会拒绝跳出插件数据目录的 `..` 路径。插件配置请使用 `api.get_config()` / `api.set_config()`，不要直接读写启动器的 config.json。

---

## 5. 核心原则

- **核心组件不插件化**：启动/实例/下载/设置/AI 是底座，插件只承载**非核心/可选/锦上添花**功能。
- **静态加载**：改插件需重启；启停靠 `settings["plugins_disabled"]`（设置→插件 勾选）。
- **只依赖公开 api** + PySide6 / 启动器已公开的工具函数；不 import 核心内部模块改行为、不 monkeypatch 核心类。

---

## 6. 安全约束（危险 import / 调用）

插件可能来自 **AI 生成** 或 **第三方**（不可信）。为防恶意插件，plugin_manager 安装/加载时做**静态审计**，但**不静默拒绝**——而是**把发现的问题列给安装者**（它 import / 调用了什么），由安装者判断信任。

**危险 import**（会被审计并报告给安装者）：
- `os` / `os.path`（文件系统）— 部分插件可能合理使用
- `subprocess` / `shutil` — 启动进程/复制文件
- `socket` / `requests` / `urllib` — 网络
- `ctypes` / `winreg` — 系统底层
- `importlib` / `importlib.util` — 动态导入(潜在混淆)

**危险调用**（被审计并报告）：
- `os.system` / `os.popen` — 执行 shell
- `eval(` / `exec(` — 动态执行代码
- `open(..., "w")` 写**系统/用户主目录**路径 — 越界写文件
- `pickle.loads` — 反序列化(可执行恶意 payload)

> **默认允许、但标记**：`import os` 用于读写 `AMCL/` 数据目录是合理场景；审计只做"提示 + 标注信任"，不一律拒绝。

---

## 7. 信任分级

插件安装时记录 `trust` 来源，UI 展示：

| 来源 | trust 值 | 显示 |
|---|---|---|
| 官方仓库（erfanyo/Agent_Minecraft_Launcher）| `official` | 官译 |
| 第三方仓库 | `third_party` | 第三方 |
| **AI 生成（create_plugin 工具）** | `ai_generated` | **AI 生成 · 未审核**（安装前提示）|

> AI 生成的插件默认 `ai_generated`，安装/加载前提示"这是 AI 生成的插件，先检查它 import/调用了什么（见 §6 审计）再决定是否启用"。

---

## 8. 示例

完整可运行示例见 `plugins/hello.py`（同时注册 工具/页面/设置/技能 四类）。最小模板见 `plugins_templates/插件模板.md`。
