# AgentMC Bridge 协议文档

本文档定义 **bridge-mod**（启动器桥接 mod）与 **启动器** 之间的所有通信协议。
面向实现者（mod Java 侧 + 启动器 Python 侧）与调试，机器可读优先。

> 版本：v1（2026-08）
> 适用：Fabric / NeoForge / Forge（MultiLoader，common 共享；跨版本 API 差异见各平台适配层）。

---

## 0. 使用场景

本协议的触发场景分三类，含义不同，协议字段随场景变化：

| 场景 | 说明 | /ai 是否适用 | 指令口是否适用 |
|---|---|---|---|
| **单机集成服务器** | 玩家坐在启动器前玩自己的世界 | ✅ 玩家敲 `/ai` | ✅ |
| **局域网开放** | 对局域网开放，朋友连进来 | ✅ 朋友玩家敲 `/ai` | ✅ |
| **纯服务端（dedicated）** | 无游戏内玩家（或管理员用 console） | ⚠️ 通常无player | ✅ 主通道 |

> 纯服务端：`/ai` 文件交换主要服务"有玩家"场景；纯服务端/自动化场景请走 **TCP 指令口**（可 `as_player` 选玩家身份，缺省控制台身份）。

---

## 1. 数据目录约定

所有数据文件位于**实例运行目录**（版本隔离 = `versions/<id>/`，未隔离 = 游戏目录）下的 **`.bridge/`** 子目录。

```
<game_dir>/versions/<id>/.bridge/
├── token.txt              鉴权令牌(启动时生成)
├── command_result.json    指令执行结果(最新一条)
├── ai_request.json        /ai 请求(mod → 启动器)
├── ai_reply.json          /ai 回复(启动器 → mod)
├── recipes.json           配方导出
├── items.json             物品属性导出
├── keybindings.json       按键绑定导出
└── bridge_mod.log         mod 日志(调试用)
```

数据目录由 `BridgeIO.bridgeDir(server)` 决定；`BridgeIO` 需按 MC 版本适配
（如 1.20.1 `server.getServerDirectory()` 返回 `File`，1.21.1 已是 `Path`）。

---

## 2. TCP 本地指令口（主通道）

mod 在服务器启动后监听 `127.0.0.1:26100`（仅本机，IPv4）。启动器读 `token.txt` 作简单鉴权。

### 2.1 请求（启动器 → mod）

单行 JSON（`\n` 结尾）：

```json
{"seq": 1, "command": "weather rain", "token": "<token>", "as_player": ""}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `seq` | number | 否 | 请求序号，回包原样带回 |
| `command` | string | 是 | 指令（可带 `/` 前缀，mod 不强制）|
| `token` | string | 是 | `token.txt` 内容，鉴权 |
| `as_player` | string | 否 | 玩家名或 UUID。**指定时以该玩家身份执行**（位置/权限/`@p` 按玩家）；留空或缺失 = **服务端控制台身份**（level 4）|

### 2.2 响应（mod → 启动器）

单行 JSON（`\n` 结尾），同时落盘 `command_result.json`：

```json
{"seq": 1, "command": "weather rain", "result": "Set the weather to rain", "success": true}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | number | 对应请求 |
| `command` | string | 原指令 |
| `result` | string | `CommandSource` 捕获的反馈文本（`sendSuccess`/`sendFailure`）|
| `success` | boolean | 是否成功（done && success）|

### 2.3 执行身份规则（关键）

执行指令时用 `Commands.performPrefixedCommand(source, cmd)`，`source` 身份取决于 `as_player`：

- **`as_player` 为空** → `server.createCommandSourceStack()`（**控制台身份，level 4**，全部指令）；
- **`as_player` 指定且在线的玩家** → `source.withEntity(p).withSource(p)`（**该玩家身份**，用玩家自己的权限等级）；
- **`as_player` 指定但玩家不在线** → 回 `success:false`，`result` 注记"玩家不在线"，不执行。

> **权限自动裁决**：非 OP 玩家（level 0）以玩家身份执行 `/op`、`/give @p`、`/gamemode` 等，
> MC 服务器执行时**自带的权限体系**会拒绝——不需要 mod/启动器额外判断。这正体现协议"以玩家身份执行 = 利用 MC 自身权限管理"的设计。

### 2.4 错误

- `bad token`：token 不匹配 → `{"error":"bad token"}`
- 其他：`success:false` + `result` 含原因

---

## 3. `/ai` 游戏内 AI 入口（文件交换）

mod 注册 `/ai <描述>`，玩家在游戏内调用；启动器轮询 `ai_request.json`，处理并写 `ai_reply.json`，mod 回显到玩家聊天栏。

### 3.1 请求（mod → 启动器）：`ai_request.json`

```json
{"seq": 1, "text": "怎么合成终极感应供应器", "ts": 1620000000000,
 "protocol_version": 2, "player": "Steve", "is_op": true, "permission_level": 4,
 "server_type": "singleplayer", "is_integrated_owner": true, "exec_mode": "player",
 "pos": "100,64,200", "dim": "minecraft:overworld",
 "held": "minecraft:diamond_sword"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `seq` | number | 序号（递增），启动器回包带同 seq |
| `text` | string | 玩家问题（`/ai` 后的内容，已去掉 `--console` 前缀标记）|
| `ts` | number | 毫秒时间戳 |
| `player` | string | 发出玩家名（纯服务端/无实体 = 空或 "console"）|
| `is_op` | bool | 该玩家是否 level ≥ 2（**mod 侧用 `src.hasPermissions(2)` 判定**）|
| `permission_level` | number | 当前 `CommandSourceStack` 的实际权限等级（0–4）|
| `server_type` | string | `singleplayer` / `lan` / `dedicated`；`lan` 仅代表已开放局域网，**不代表发起者是房主** |
| `is_integrated_owner` | bool | 集成服世界的房主；只有该字段为 true 才可把单机/LAN 发起者当作本机房主 |
| `protocol_version` | number | 当前为 2；缺失说明是旧 bridge-mod，启动器不得执行写指令 |
| `exec_mode` | string | `"player"`（默认）/ `"console"`（仅 level 4 玩家可选）|
| `pos` | string | 玩家坐标 `"x,y,z"`（上下文注入用）|
| `dim` | string | 维度 id `"minecraft:overworld"` |
| `held` | string | 主手物品 id |

### 3.2 回复（启动器 → mod）：`ai_reply.json`

```json
{"seq": 1, "text": "终极感应供应器需要……", "ts": 1620000001000}
```

mod 轮询到 **seq 匹配** 的回复后，回显 `[AI] <text>` 给**发起玩家**（`player`），并删除该回复文件（避免重复回显）。

### 3.3 `/ai` 身份规则（核心）

玩家敲 `/ai` 的形式：

```
/ai <描述>            # 默认:AI 执行指令用【该玩家身份】
/ai --console <描述>  # 仅 level 4 玩家可选:AI 执行指令用【控制台身份】(level 4)
```

| 玩家等级 | 默认身份 | `--console` 可选？ | 说明 |
|---|---|---|---|
| **level 4** | 玩家身份 | ✅ 可选 | 切控制台(level 4)，最全指令 |
| level 2-3（OP）| 玩家身份 | ❌ | 强制玩家身份（用自己级别执行）|
| level 0-1 | 玩家身份 | ❌ | 强制玩家身份；高级指令被 MC 权限体系拒绝 |

**规则**：
- `exec_mode` 默认 `"player"` → 启动器 AI 执行指令用 `as_player=<player>`（该玩家身份）；
- 仅当 `is_op` 且玩家是 **level 4** 且请求显式 `--console` → `exec_mode="console"` → AI 用控制台身份；
- **非 level 4（含普通 OP）填 `exec_mode="console"` → mod 侧忽略**（mod 在解析 `/ai` 时，对非 level 4 玩家不接受 `--console`；即使漏报，启动器侧也按 `is_op`/level 兜底强制玩家身份）。

> **`--console` 解析在 mod 侧**（`AiChat.submit` 读文本前缀）：非 level 4 忽略该标记；
> mod 上报 `player` + `is_op` + `exec_mode`，启动器照做，不再自行判断权限。

### 3.4 与 FTB Quests 任务指令的关系

FTB Quests 的 **Command Reward**（任务奖励指令）有 `Run as Player` / `Run with elevated permission` 两档，
执行身份 = 玩家身份 或 服务器控制台身份。它与 `/ai` 是**完全独立的触发机制**：
- FTB：玩家**完成任务**时由 FTB 自己触发执行指令；
- `/ai`：玩家**主动敲 /ai** 时 mod 上报身份、启动器 AI 发指令。

两者各自用独立 command source，**互不干扰、互不抢权限**。日志中均可能标记为对应身份（FTB 控制台档和 `/ai --console` 都可能在 server 日志标记 console），属正常现象。

---

## 4. 数据导出

mod 在服务器启动完成后导出（供启动器 AI / 配方 / 属性比较用）。

### 4.1 `recipes.json`（配方）

```json
[ {"id": "minecraft:crafting_table", "type": "minecraft:crafting",
   "output": {"item": "minecraft:crafting_table", "count": 1},
   "ingredients": [{"item": "minecraft:oak_planks", "count": 4}, ...]} ]
```

| 字段 | 说明 |
|---|---|
| `id` | 配方 id（`<ns>:<path>`）|
| `type` | 配方类型（`minecraft:crafting` / `smelting` / mod 自定义）|
| `output.item/count` | 产物物品 id + 数量 |
| `ingredients[].item/count` | 原料（每种取第一个可用物品代表）；空/任意为 `item:"(空/任意)",count:0` |

### 4.2 `items.json`（物品属性）

```json
[ {"id": "minecraft:diamond_sword", "max_stack": 1,
   "attributes": {"attack_damage": 7.0, "attack_speed": 1.6},
   "food": null, "tags": ["minecraft:swords"]} ]
```

| 字段 | 说明 |
|---|---|
| `id` | 物品 id |
| `max_stack` | 最大堆叠 |
| `attributes` | 装备属性（`attack_damage`/`attack_speed`/`armor`/`armor_toughness`/`knockback_resistance`/`movement_speed`）|
| `food` | 食物属性（`nutrition`/`saturation`）；非食物为 null/缺省 |
| `tags` | 物品标签（含工具等级推断用）|

### 4.3 `keybindings.json`（按键绑定，客户端）

```json
[ {"key": 340, "name": "key.attack", "display": "攻击", "category": "gameplay", "mod": "minecraft"} ]
```

---

## 5. 鉴权

- 指令口：TCP `token.txt`（mod 启动时生成随机 UUID 去掉横线写入）；启动器读文件作请求 token。
- `/ai` 文件交换：无需 token（仅本机文件，经 `.bridge` 目录）；但 mod 侧**所有入口应校验玩家合法**（在线实体）。

---

## 6. 游戏内 AI 额度 / 权限（启动器端配置）

`/ai` 底层走服主（启动器主人）的 AI API，多人联机可被刷。以下限制**全部在启动器端配置**，游戏内玩家不可改：

| 设置项 | 默认 | 说明 |
|---|---|---|
| 每日额度 | 50 次/天 | 全实例 `/ai` 每天总发言上限；0=不限；用超回提示不调 API |
| 每玩家冷却 | 5 秒 | 同一玩家两次 `/ai` 最小间隔；防单玩家刷 |
| 豁免名单 | 空 | 启动器主人认可的"服主/管理员"（逗号分隔），无限用、不计入总额度 |

> **豁免名单语义**：不是默认"开服者"，而是启动器主人**手动填**的账号。局域网开放时开服者往往不敲 `/ai`，豁免名单应填**实际会用的朋友**。额度用尽提示"去跟服主要"——服主 = 在设置里加豁免名单的启动器主人。

**权限拦截（OP 细分）**：集成服房主、OP/level4 玩家才可获得指令写工具；LAN 客人不能仅因世界已公开而获得房主权限。旧 bridge-mod 未上报协议版本/玩家身份时，启动器只提供只读工具并提示升级。实际执行始终带 `as_player`，由 MC 权限体系**强制裁决**，双保险。

---

## 7. 版本适配说明

| API / 行为 | 版本差异 | 处理 |
|---|---|---|
| `server.getServerDirectory()` | 1.20.1 返 File / 1.21.1 返 Path | `BridgeIO` 按版本适配 |
| 配方原料 `ing.getItems()` | 1.21 直接返 `ItemStack[]` | 适配层 |
| `CommandSourceStack.withEntity`/`withSource` | 1.20.1→1.21.4 稳定 | common 共享 |
| 玩家查询 `PlayerList.getPlayerByName/getPlayerByUUID/getPlayers` | 稳定 | common 共享 |
| 权限等级 `hasPermissions(int)` | 0-4，稳定 | 判定用 `hasPermissions(2)`（OP）/ `hasPermissions(4)`（级别4）|

---

## 8. 待办 / 已知限制

- [x] mod 侧 `AiChat` 上报身份、权限等级、环境、房主身份与协议版本（v2）
- [x] mod 侧 `--console` 解析：level 4 才接受标记
- [ ] 编译发布各平台 / 版本 v0.2.0 jar（需构建环境，见 README）
- [x] 启动器侧 `in_game_ai` 按身份/环境挂工具，并强制以发起玩家身份执行
