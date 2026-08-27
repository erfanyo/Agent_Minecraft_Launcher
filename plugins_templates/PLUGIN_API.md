# plugin_manager 插件开发 API 文档

> 面向**人类开发者**如何手写启动器插件。插件 = `plugins/<名字>.py`，提供 `register(api)`，启动时被静态装载。
> 安全：插件是本地代码，但**可能来自 AI 生成或第三方**（不可信），见 §6 安全约束 & §7 信任分级。

---

## 1. 最小插件

```python
PLUGIN_ID = "my_plugin"          # 插件唯一 id(用作工具名/设置项前缀)
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
| `register_gui_page(label, build_fn)` | 注册 GUI 页面/章节 | 写 `GUI_PAGES` |
| `register_main_tab(label, build_fn)` | 注册主标签页(与 下载新资源/设置 平级) | 写 `MAIN_TABS` |
| `register_settings_page(build_fn)` | 注册独立设置页(左菜单单开一行) | 写 `_PLUGIN_META` |
| `register_setting(key, description, default=None, choices=None)` | 登记设置项(占位) | 写 `SETTINGS` |
| `register_skill(skill_cls)` | 注册技能(Skill 子类) | 追加 `SKILLS` |
| `register_language_pack(pack_id, name, pack, lang="")` | 注册语言包(文本覆盖) | 写 `LANGUAGE_PACKS` |

### 2.1 `register_tool`
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

### 2.2 `register_gui_page` / `register_main_tab` / `register_settings_page`
三者 `build_fn()` 都返回一个 `QWidget`；`register_main_tab` 与 下载新资源/联机/设置 平级，`register_settings_page` 在设置左菜单单开一行。

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
| `PLUGIN_ID` | str | ✅ | 插件唯一 id（作为工具/设置项前缀）|
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

> 若需要 `api.data_dir()`，插件须在 `register` 里调用 `api.data_dir()`；当前若未提供该方法，可自行用 `paths.CONFIG_DIR + "/plugins_data/" + PLUGIN_ID` 获取。详见 `paths.CONFIG_DIR`。

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
