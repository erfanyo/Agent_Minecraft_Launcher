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

## 兼容目标(2026-08 更新)

**策略:先兼容 mod 生态活跃/多的版本**(而不是铺开所有版本):
- ✅ Fabric 1.21.1(已编译发布)
- ✅ NeoForge 1.21.1(已编译发布)
- 🎯 目标:**1.20.1**(老版本里 mod 生态最活跃)、**1.21.4**(1.21 系列主流)
- ⏳ Forge(1.19 及以前)晚点再说
- 每个新版本 = 改 loom/neogradle 的 MC 版本重编译 + 版本表加条目(15 秒级)

## 功能路线图(频繁迭代)

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

### 🧠 游戏内 AI 入口(待实现 · 启动器侧已就绪)
- **需求**:玩家在游戏里敲 `/ai <内容>`,内容交给启动器 AI 处理,结果回显出到游戏聊天栏。
- **实现(文件交换,复用 .bridge 机制)**:
  - **mod 侧(待做,需编译)**:注册 `/ai <内容>` 命令 → 写 `.bridge/ai_request.json`
    `{"seq":1,"text":"<内容>","ts":...}`;并轮询 `.bridge/ai_reply.json`(seq 匹配)→ `tellraw` 回显。
  - **启动器侧(✅ 已做)**:`in_game_ai.py`(InGameAI 轮询 + make_answerer 按 ai_in_game 作答),
    发现新 seq → 调 AI → 写 `.bridge/ai_reply.json` `{"seq":1,"text":"回复","ts":...}`。
- **状态**:启动器侧可用且可测(模拟 request→reply 通过);mod 侧代码待写 + 需 JDK/Gradle 编译。

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

需要:JDK(带 javac)+ Gradle(或 gradle wrapper,首次联网下载)。

**构建状态(2026-08)**:✅ **fabric 平台编译通过**(产物 `fabric/build/libs/fabric-0.1.0.jar`)。
forge / neoforge 平台插件版本待适配(见下)。

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

**当前构建范围**:只构建 fabric(common 源码直接并入 fabric 编译单元,
见 `fabric/build.gradle.kts` 的 sourceSets)。forge / neoforge 子项目
已从 `settings.gradle.kts` 的 include 移除,待适配它们的 gradle 插件版本
(ForgeGradle 6.0.x、NeoGradle 7.0.x)后再加入。

## 老版本兼容策略(1.7.10 等)

**单个 mod 项目同时支持 1.7.10 → 1.21.1 不现实**,原因:
- 工具链:1.7.10 需 JDK 8 + 老 ForgeGradle;1.21.1 需 JDK 21 + 现代工具链
- 加载器:Fabric 不支持 1.14 以前;NeoForge 仅 1.20.1+;老版本只有老 Forge
- API:数据导出代码依赖 1.20.5+ 的 API,老版本要按版本重写

**现实路径**:
1. 现代版本(1.20.1+ / 1.21.x):用本 mod(当前骨架)
2. 老版本(1.7.10 等):继续用"Lan Server Properties + 模拟按键 + 日志反馈"
   轻量方案;如以后确实重视老版本,再单独建老工具链的分支项目(功能打折,
   数据导出在老 API 上做不了,只能做指令桥/自动 RCON)


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
