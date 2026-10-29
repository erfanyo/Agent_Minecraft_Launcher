# bridge-mod(启动器桥接 mod)

启动器与游戏之间的"桥梁",多平台 mod(Fabric + Forge + NeoForge)。
工作区位置:启动器项目根目录 `bridge-mod/`。

> ⚠️ **测试阶段声明**:本 mod 目前处于**测试阶段**,功能可能频繁变化、存在 bug,
> 仅用于开发者/尝鲜测试,暂不建议向普通朋友分发。
> 正式版(v1.0)计划加入:**正版登录支持**(未来有可能,视需求而定)。

## 为什么不用"非 mod"方案

论证过 Java Agent(-javaagent 字节码改写)方案:能 hook 集成服务器开 RCON,
但每个 MC 版本类结构都要适配、脆弱、无生态,且做不了数据导出等高级功能 → 放弃。
采用多平台 mod(社区 MultiLoader 模板,版本适配成熟)。

## 兼容目标（2026-09 修正）

bridge-mod 有两种**实现路线**，不是功能档位：现代版本使用完整 API；旧版因加载器与
Minecraft API 太旧，使用独立兼容实现。两者都以“在该版本 API 允许范围内尽量提供完整功能”为目标。

短期目标版本：**1.21.1、1.20.1、1.19.2、1.18.2、1.16.5、1.12.2、1.7.10**。

| 版本段 | 加载器 | 实现路线 | Java 运行时 | 当前状态 |
|---|---|---|---|---|
| 1.21.1 | Fabric / NeoForge | 完整 API | 21 | Fabric 已有可用产物；其余待重新核验发布 |
| 1.20.1 / 1.19.2 / 1.18.2 | Forge 优先，Fabric 次之 | 尽量完整的适配 API | 17 | Forge 1.20.1、1.19.2 已构建验证；1.18.2 待构建 |
| 1.16.5 / 1.12.2 | Forge | 旧版兼容实现 | 8 | 独立旧工具链已建立、核心双向指令已编译；待逐版本实机联调 |
| 1.7.10 | Forge | 旧版兼容实现 | 8 | 待建立独立工具链 |

**1.21.1 以下的适配优先级：Forge > Fabric > NeoForge。**旧版兼容实现至少保留双向指令、结果回传和启动器下载/安装兼容；能导出的配方、物品、
按键与游戏内 AI 上下文则按各版本 API 逐项补齐，并通过能力标记告诉启动器实际可用项。

## 功能路线图(频繁迭代)

### 整合包引导与角色控制扩展（规划，尚未实现）

**Minecraft 1.7.10 Forge 和 1.12.2 Forge 是必须覆盖的版本**，与现代版本共同作为
整合包引导系统的目标。旧版整合包同样需要配方解释、进度引导和现场辅助；不能只保留
指令通道就视为完成支持。各版本分阶段实现并单独验收，通过能力声明报告已支持、
未支持和需要额外适配的功能。1.7.10 当前仍待建立工具链，以上是目标而非已实现声明。

引导功能规划包括物品/配方目标标记、任务进度关联、按需库存查询、带来源和版本条件的
知识检索、截图与机器界面解释、界面箭头提示、世界投影和分阶段搭建。任务与配方查看器
采用可选适配器：按实际版本对接 FTB、其他任务系统以及 NEI/JEI/EMI，不要求所有版本
安装相同组件。旧版物品身份保留 metadata 和必要的 NBT，不能只用显示名称匹配。

搭建模式统一为四档：**关、投影、消耗物品搭建、不消耗物品搭建**。服务端校验权限、
材料和环境；非消耗搭建需要对应授权。方案包含布局、配置步骤、环境条件与验收规则，
方块放置完成和设施运行成功分别记录。

架构同时为以下可能用法预留接口，不将其计入首版引导功能的完成条件：

- **AI 通关 MC 挑战**：让 AI 根据观察制定目标，控制角色行动，记录过程并检查完成条件。
- **多个 AI 角色协作**：由多个 agent 分担采集、运输、建设、探索等工作，并共享必要的任务状态。
- **RTS 式玩法**：玩家选择多个角色、分派任务、查看进度，并随时暂停或接管角色。

预留的协议职责如下；名称与字段尚待正式协议设计，不代表现有可调用 API：

| 接口类别 | 预留内容 |
|---|---|
| 观察 | 玩家/角色状态、局部世界、界面、按需库存查询；支持范围、分页和变化订阅 |
| 行动 | 移动、朝向、交互、挖掘、放置、物品与界面操作；区分底层动作和需要适配的高层技能 |
| 长任务 | 任务编号、开始、进度、结果、超时、暂停与取消；取消后释放持续按键等控制状态 |
| 角色与控制权 | 独立角色 ID、会话、控制权租约、玩家接管；避免多个控制器同时操纵同一角色 |
| 协作 | 任务分派、资源/区域预约、冲突反馈和共享状态，避免重复取料或同时修改同一位置 |
| 能力与权限 | 按版本、服务端和角色声明能力；服务端逐项校验动作、范围及消耗规则 |
| 评估与回放 | 记录动作及结果、失败原因和挑战完成条件，支持复盘与用量统计 |

跨版本共享数据协议和行为语义，各版本使用独立游戏 API 适配；路径规划、角色实体、
寻路执行与多 agent 调度器的具体实现另行选择。预留多人协议不等于已经具备机器人角色。
不支持的动作必须明确返回能力不足，不得悄悄替换为越权指令或免材料搭建。
角色控制默认关闭，启用后仍受服务端授权约束；搭建四档独立控制搭建行为，不自动授予
移动、战斗或其他角色控制权限。现有最新单条文件交换方式需要扩展会话和请求隔离后，
才能承载多角色并发，不能直接作为多 agent 通信协议。

1. **指令桥(核心)**:
   - 进世界自动开 RCON(集成服务器也开,免"对局域网开放")
   - 命令执行结果写回文件(自定义 CommandSource),启动器读文件拿 100% 准确反馈
   - 数据目录:实例运行目录 `.bridge/`(如 `.bridge/command_result.json`)
2. **JEI/配方数据导出**:
   - 遍历 `RecipeManager` 把全部配方 dump 成 `.bridge/recipes.json`
   - 遍历注册表把物品属性 dump 成 `.bridge/items.json`
     (攻击伤害/护甲/速度/食物/标签等,挖掘等级按工具标签推断)
   - 启动器侧 `recipe_graph.py` 做套娃合成计算 + 物品参数比较,AI 据此指导合成
3. **指令库同步**:mod 与启动器指令中心互通(自定义指令/NBT 模板)
4. **未来**:更多启动器相关功能(游戏内状态回传、自动化操作等)

### 🧠 游戏内 AI 入口(已实现 · fabric 1.21.1 已编译)
- **需求**:玩家在游戏里敲 `/ai <内容>`,内容交给启动器 AI 处理,结果回显出到游戏聊天栏。
- **实现(文件交换,复用 .bridge 机制)**:
  - **mod 侧(✅ 已做)**:`AiChat.java` 注册 `/ai <内容>` → 写 `.bridge/ai_request.json`
    `{"seq":1,"text":"<内容>","ts":...}`;后台线程轮询 `.bridge/ai_reply.json`(seq 匹配)→ 回显到发起者聊天窗。
  - **启动器侧(✅ 已做)**:`in_game_ai.py`(InGameAI 轮询 + make_answerer 按 ai_in_game 作答),
    发现新 seq → 调 AI → 写 `.bridge/ai_reply.json` `{"seq":1,"text":"回复","ts":...}`。
- **状态**:mod 侧(fabric 1.21.1)与启动器侧均已就绪;本地测试 jar 已装到 `fabric-loader-0.19.3-1.21.1`。
  其余平台(neoforge/forge)与更多 MC 版本待适配编译。

### 服务端 / 多人游戏 AI 接入（后续方案，尚未实现）

由服主选择向玩家开放的方式及权限范围：

1. **服主提供 AI API**：玩家的请求交给服主配置的 AI 处理；服主决定谁能使用及可用额度，API 凭据只保存在服务端，不下发给玩家。
2. **按权限开放服务器控制面板**：服主决定每名玩家可查看和操作的服务器能力；AI 调用使用玩家个人的配置和额度，服务端按该玩家获授的权限执行操作。

两种方式都需要明确玩家身份、权限与用量边界。多人请求应独立排队和回传，避免当前单个 `ai_request.json` / `ai_reply.json` 被并发请求覆盖。

## 目录结构

```
bridge-mod/
├── settings.gradle.kts      # 聚合 common / fabric / forge / neoforge
├── build.gradle.kts         # 根构建
├── common/                  # 共用代码(纯 Java + Minecraft 标准 API)
│   └── src/main/java/com/agentmc/bridge/
│       ├── BridgeCore.java      # 入口协调:服务器启动/停止时调用各模块
│       ├── RconAutoOpener.java  # 自动开 RCON(按版本适配,标注 TODO)
│       ├── CommandResultSink.java # 命令结果写回 .bridge/command_result.json
│       ├── RecipeExporter.java  # 配方 dump → .bridge/recipes.json
│       └── ItemExporter.java    # 物品属性 dump → .bridge/items.json
├── fabric/                  # Fabric 平台入口 + fabric.mod.json
├── forge/                   # Forge 平台入口 + mods.toml
└── neoforge/                # NeoForge 平台入口 + mods.toml
```

## 构建

本机批量构建入口是项目根目录的 `build_bridge_all.ps1`。直接执行会构建当前已实现的
8 个变体，也可用 `-Only forge-1.16.5,neoforge-1.21.1` 选择目标。
脚本为每个目标选择 Gradle/JDK，执行 clean/build（跳过测试），成功后复制到 `bridge-mod/dist/`。
完整日志保存在 `.tmp/bridge-build-logs/`；任一目标失败时脚本返回非零退出码，不会用旧 JAR 冒充成功产物。
编译通过仅代表构建成功，游戏内功能仍需实机验证。

Forge 1.16.5 当前使用 ForgeGradle 5.1 + Gradle 7.6.4，Gradle 运行于 JDK 17，编译任务使用 JDK 8；
Forge 1.12.2 则使用 ForgeGradle 2.3 + Gradle 4.10.3 + JDK 8。

需要:JDK(带 javac)+ Gradle(或 gradle wrapper,首次联网下载)。

### 要准备的 JDK（构建与运行矩阵）

| MC 目标版本 | 游戏/Mod 运行 Java | bridge 构建 JDK | 备注 |
|---|---:|---:|---|
| 1.21.1 | 21 | 21 | 现代 Fabric / NeoForge |
| 1.20.1、1.19.2、1.18.2 | 17 | 17 | 现代 Forge / Fabric |
| 1.16.5、1.12.2、1.7.10 | 8 | 8 | 旧 ForgeGradle，独立工程 |

因此开发机至少保留 **JDK 8、JDK 17、JDK 21**。不要只改全局 `JAVA_HOME`；各构建脚本
显式选择对应 JDK，旧版还要使用独立的 Gradle 用户目录和旧 ForgeGradle，避免污染现代构建缓存。

**构建状态(2026-10-08)**：0.2.0 的 8 个变体全部编译通过：Fabric 1.20.1 / 1.21.1，
Forge 1.12.2 / 1.16.5 / 1.18.2 / 1.19.2 / 1.20.1，以及 NeoForge 1.21.1。
产物在 `dist/`；本次同时生成 `bridge-mod-0.2.0.zip`、`SHA256SUMS.txt` 和 `build-manifest.json`。
字节码分别为 Java 8（Forge 1.12.2 / 1.16.5）、Java 17（1.18–1.20）、Java 21（1.21.1）。
本次修复 Forge 1.16.5 的编译参数和 MCP 方法名适配，以及 Forge 1.12.2 的 UTF-8 源码编码。
旧 JAR 已备份至 `.tmp/bridge-build-logs/previous-jars-20261008-174355/`，防止自动发现选择
历史上编号较高但源码较旧的产物。以后替换同一 MC/加载器产物时，也应移走过期版本，
或统一递增版本号；不要只覆盖低版本文件。此次未运行测试或游戏内联调。

**本机已验证的环境**(关键!):
- JAVA_HOME = `E:\Agent_Minecraft_Launcher 0.0.1\.tmp\jdk\jdk-21.0.12.1+1`
  (Temurin JDK 21 LTS,Adoptium 官方下载;重装系统后已重新就位)
- Gradle = **8.10.2**(解压于 `.tmp\gradle-dist\gradle-8.10.2`)

**⚠️ Gradle 版本坑(踩过)**:Gradle **8.13 / 8.14 移除了
`Problems.forNamespace(String)` API**,而 fabric-loom 1.6.x 依赖它,
会导致 `LoomProblemReporter` 实例化失败。**必须用 Gradle 8.10.x**。
Gradle 8.10 官方 javadoc 确认该方法存在,8.13 已移除。

**构建命令**:
```
set JAVA_HOME=E:\Agent_Minecraft_Launcher 0.0.1\.tmp\jdk\jdk-21.0.12.1+1
set GRADLE_USER_HOME=E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-home
cd bridge-mod
E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-dist\gradle-8.10.2\bin\gradle.bat :fabric:build --no-daemon
```
> 产物字节码版本 = 21(匹配 MC 1.21.1 的 Java 21 运行时)。
> 构建需联网(首次下载 MC 依赖几百 MB,GRADLE_USER_HOME 里缓存)。

**Forge 1.20.1 构建命令**:
```
set JAVA_HOME=D:\programs\Java\jdk-17.0.12
set GRADLE_USER_HOME=E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-home-forge-1.20.1
E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-dist\gradle-8.10.2\bin\gradle.bat -p bridge-mod :forge:build --no-daemon
```
Forge 子项目直接编译 `common` 与 `common-1.20.1` 源码，避免把 1.21 API 混入 1.20.1 产物。

## 老版本兼容策略(1.7.10 等)

**单个 mod 项目同时支持 1.7.10 → 1.21.1 不现实**,原因:
- 工具链:1.7.10 需 JDK 8 + 老 ForgeGradle;1.21.1 需 JDK 21 + 现代工具链
- 加载器:Fabric 不支持 1.14 以前;NeoForge 仅 1.20.1+;老版本只有老 Forge
- API:数据导出代码依赖 1.20.5+ 的 API,老版本要按版本重写

**现实路径**：为旧版建立独立 ForgeGradle/JDK 8 工程，而不是放弃 bridge-mod。
旧版优先实现双向指令通道，再按 API 能力补数据导出与 `/ai` 上下文；启动器下载页始终
兼容上述目标版本，即使某版本暂时只能提供部分 bridge 能力。


## 分发策略(2026-08 已定)

**不做启动器内置源码自动编译**(朋友电脑没有 JDK/Gradle,不可行)。
采用**预编译 jar + 双通道分发**:

1. **发布**:编译好的 jar(各平台)上传 **Modrinth**(主,玩家可手动装)+ GitHub Releases(备份)
2. **离线通道**:三平台 jar 打进启动器 exe,一键配置时直接复制到实例 mods(零联网)
3. **在线通道**:启动器「检查桥 mod 更新」从 Modrinth/GitHub 拉新 jar

每次迭代 = 本地编译 → 上传新 jar → 更新启动器内置版本表。

## 与启动器的约定

- 数据文件:实例运行目录(版本隔离 = `versions/<id>/`)下的 `.bridge/` 子目录
- `recipes.json` 结构:`[{id, type, output:{item,count}, ingredients:[{item,count}...]}]`
- `items.json` 结构:`[{id, name, max_stack, attributes:{attack_damage, armor, ...}, tags:[...]}]`
- `command_result.json`:`{seq, command, result, time}`(每次命令一条,启动器读最新)
