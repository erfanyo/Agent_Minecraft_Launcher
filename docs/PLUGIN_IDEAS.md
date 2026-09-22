# 插件方向待办

## 冲正式版(1.0)先丢包袱

正式版前先减负，而不是加功能。判断标准：**这个功能是不是「大多数玩家每次都用」**。
不是的，就是包袱——要么转插件，要么先摘掉。

- 待转插件：KubeJS 查看（见下）、魔改类工具。
- 转插件后的核心只保留：**装/管/启动实例、下载资源、服务端基础管理、AI 助手、设置**。

理由：核心每次发版都要为这些功能做兼容与回归；插件可以各自走，作者按需装。
**这不是砍功能，是换承载方式**——能力还在，只是不再默认压在所有人身上。

## 翻译 API 插件

核心内置的 Mod 描述翻译支持本地模型（默认）与用户已配置的云端 OpenAI 兼容模型。

以后如确有需求，再以插件方式接入专用机器翻译 API（例如术语库、批量翻译、按语言/地区计费的服务）。插件应：

- 使用插件自己的 API 配置页和密钥存储；
- 只接收待翻译文本，不读取启动器其他数据；
- 明示服务商、联网与计费情况；
- 保持 `mod_translate` 的缓存/降级接口兼容，失败时显示原文和原因。

不在核心中预置第三方机翻服务，避免账户、地区、费用与隐私策略绑死启动器。

## 魔改类功能一律优先考虑做成插件

魔改是**整合包作者**的需求，不是普通玩家的。这类功能有几个共同点，都指向「不该进核心」：

- 目标用户很少（作者本人 + 少数服主），但功能本身可以很重；
- 强依赖具体整合包的写法、mod 组合与命名习惯，核心不可能预置全；
- 需求变化快，进核心就要长期背着兼容与维护成本。

所以**能力边界定在「作者能自己装插件、自己配」**，核心只负责提供稳定的注册点
（AI 工具 / 页面 / 中心页 / 设置页 / 技能）。以后遇到魔改类需求，先问「能不能插件化」，
再问「要不要进核心」。

## KubeJS 查看/编辑 → 插件

核心里的 KubeJS 页（服务端详情的脚本查看器）应当**整体转为插件**。它天然满足上面那条：
只有整合包作者会打开，普通玩家不会关心 `server_scripts` 里有什么。

需要注意的两点：

- **保留「只读查看」的能力**，而且它不只是编辑的附带品：脚本报错会让服务端直接起不来，
  那时读脚本是唯一的排查手段。转插件后这个能力也要一起带走，不能因为「编辑器插件」
  没装就看不了。
- 插件应当顺带做**报错定位**（把日志里的 KubeJS 报错关联到具体文件与行），
  这比编辑本身更有价值——现存脚本里的问题往往不是「写错了」，而是缺补丁/缺依赖
  （本项目就踩过：`counter.js#501` 的 `getIngredients` 报错，根因是缺 `hotai` 补丁数据）。

## 配方可视化编辑器（插件）

**目标**：用 Minecraft 那种「摆格子」的方式拼合成表，而不是让作者写 JS。
左原料槽 + 中间箭头 + 右产物槽，配物品检索；保存后游戏内 `/reload` 生效。

**为什么值得插件化**：配方是结构化数据（几个槽位 + 产物 + 时间），本该用图形界面拼。
但它只对整合包作者有价值，普通玩家一辈子用不到一次，放核心纯属增加体积与维护面。

### 两个必须写在前面的事实

1. **KubeJS 配方是「代码」，不是「数据文件」。** 没有 `recipes.json` 这种数据文件——
   配方要么写在 `.js` 里调 `event.custom({...})`，要么用 `event.recipes.xxx()`。
   因此编辑器**必须生成 JS 代码**。可行做法是生成一段显式 JSON 的 `event.custom`：

   ```js
   event.custom({
     "type": "kaleidoscope_tavern:barrel",
     "carrier": { "item": "kaleidoscope_tavern:empty_bottle" },
     "fluid": "kaleidoscope_fruit_brew:pineapple_juice",
     "ingredients": [{ "item": "minecraft:sugar_cane" }],
     "result": { "item": "kaleidoscope_world_liquor:pina_colada" },
     "unit_time": 2400
   })
   ```

   写进插件**自己独占**的文件（如 `kubejs/server_scripts/<plugin>_recipes.js`），
   **绝不改写作者手写的脚本**。

2. **网格表达不了程序化逻辑。** 作者脚本里常见「遍历某类型全部配方、按产物查表替换
   材料」这类循环/查表，图形编辑器永远做不了也不该做。能力边界说清楚：
   **编辑器负责「加/改单个配方」，批量生成逻辑仍归 JS**，两者并存互不干扰。

### 待定的设计问题

- **配方类型**：不同类型字段完全不同，必须逐个注册。建议先做作者用得最多的一种
  （酒桶 `kaleidoscope_tavern:barrel`：carrier + fluid + ingredients + result +
  unit_time），跑通后再横向扩到 shaker、`minecraft:crafting_shaped` 等。
- **编辑范围**：只做**新建 + 管理自己建过的**（能改能删）。解析作者手写的 JS 不可靠，
  不要尝试。
- **物品来源**：优先从实例已装 Mod 的注册物品表读（bridge-mod 已有导出机制），
  读不到时允许手输 `namespace:item_id`；不要只靠 Modrinth 检索——那是 Mod 名不是物品名。

### 落地要点

- 物品格子、检索与校验逻辑做成**不依赖 Qt** 的纯模块，便于单测；
- 生成的脚本要带注释标明来源，避免作者误以为是手写的；
- 保存前**必须**先能力校验（字段是否合法、物品 ID 是否存在），不能让作者生成一段
  会让 KubeJS 报错的脚本；
- 入口挂在服务端详情的 KubeJS 区域，或注册成插件自己的主标签页。

## mod 专属文件管理 → 插件 + 「检测到 mod 就提示安装」

很多 mod 的用法就是「往某个目录里丢文件」：投影原理图、枪包、皮肤、蓝图……这类
**文件管理界面非常适合插件**，而且是插件的**发现性问题**的解法：没人会主动逛插件列表，
但**装了这个 mod 的人一定需要它对应的管理页**。

### 机制：检测到 mod → 问用户装不装插件

核心已经**实际在用这个思路**，只是写死在 `instance_manager.py`：

```python
if self._has_mod("ysm", "yes_steve_model", "yesstevemodel", "yes-steve-model"):
    self.shell.add_section("皮肤(YSM)", self._build_ysm_tab)
if self._has_mod("tacz", "timeless_and_classics", "timeless", "tac_z"):
    self.shell.add_section("枪包(TACZ)", self._build_tacz_tab)
if self._has_mod("create"):
    self.shell.add_section("投影原理图", self._build_create_schematics_tab)
if self._has_mod("kubejs"):
    self.shell.add_section("KubeJS", self._build_kubejs_tab)
```

要做的就是把这段从**硬编码**改成**插件声明 + 提示安装**：

1. 插件在元数据里声明它关心的 mod（如 `WATCH_MODS = ("tacz", "timeless_and_classics")`）；
2. 核心扫到实例装了该 mod、而对应插件**未安装/未启用**时，**问一次**用户；
3. 用户同意 → 装/启用插件；拒绝 → **记住选择，不再打扰**。

设计红线（不做就会变成骚扰）：

- **只问一次**，按「实例 + 插件」记住用户的选择（含明确的「不要」）；
- **绝不静默安装**、绝不静默启用插件；
- 只在**真的检测到 mod** 时才问，不预先推荐；
- 没有对应插件时**不要**硬塞一个残缺的内置页——宁可什么都不显示。

### 主流「需要文件管理」的 mod

按用途分组。**★ = 本项目已确认在用**（有自己的目录或已在代码里硬编码）；
其余为常见主流项，**实现时必须先核实该 mod 的目录与文件格式**（版本间可能变），
不要照抄下表当规格。

**投影 / 蓝图 / 结构**

| mod | 管理的东西 | 目录（待核实时以实测为准） |
|---|---|---|
| ★ Create（机械动力） | 蓝图 schematic | `schematics/`（`.nbt`） |
| Litematica | 投影 | `schematics/` |
| WorldEdit | 原理图 | `schematics/` 与 `config/worldedit/` |
| Axiom | 蓝图 | 各自工作目录 |
| MTS / Immersive Vehicles | 载具包 | 各 pack 目录 |
| Immersive Engineering | 工程师蓝图 | 需要核实现代版本是否仍是 `blueprints/` |
| MineColonies | 建筑蓝图 | `.blueprint` / 扫描工具产物 |
| Chisels & Bits、LittleTiles | 自定义结构 | 游戏内保存，目录待核实 |

**模型 / 皮肤 / 外观**

| mod | 管理的东西 | 目录 |
|---|---|---|
| ★ Yes Steve Model (YSM) | 皮肤（`.png` 贴图 + `.model` 绑定） | `ysm/` |
| Armourer's Workshop | 盔甲/模型 | 有导入导出流程 |
| Custom Player Models (CPM) | 玩家模型 | `config/` 下的模型目录 |
| CustomNPCs | NPC、皮肤、脚本 | `customnpcs/`、`config/CustomNpcs.cfg` |
| ★ Touhou Little Maid（车万女仆） | 自定义模型包 | `tlm_custom_pack/`（本项目 1260 个文件） |

**枪械 / 载具 / 其他内容包**

| mod | 管理的东西 | 目录 |
|---|---|---|
| ★ TaCZ（永恒枪械工坊） | 枪包（每子文件夹一个包） | `tacz/gunpack/` |
| Superb Warfare | 内容包 | 待核实 |
| Create: Gears and Tavern 等附属 | 数据/贴图包 | 各 mod 自定 |

**脚本 / 数据（见上一节）**

| mod | 管理的东西 | 目录 |
|---|---|---|
| ★ KubeJS | `.js` 脚本 | `kubejs/`（server_scripts / startup_scripts / client_scripts） |
| ★ Hotai | 补丁数据 `.badiff` | `hotai/` |
| ★ Patchouli | 手册内容 | `patchouli_books/` |
| ★ FTB Quests | 任务 `.snbt` | `config/ftbquests/` |

### 落地顺序建议

先挑**本项目已在用**的那几个（YSM / TACZ / Create / KubeJS，加车万女仆与 Hotai）做成
插件并跑通「检测→提示→安装」，把机制验证透；再按上面的表逐个补。
一次把几十个 mod 的目录写死进核心，正是要避免的老路。


