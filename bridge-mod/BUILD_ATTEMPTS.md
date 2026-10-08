# bridge-mod 全平台构建记录 —— 统一 0.2.0

> 记录时间:2026-10-04
> 状态:**7/8 变体已编译并校验通过;forge-1.16.5 未完成;GitHub Release 未发布(用户要求先暂停)**

## 1. 目标

把所有 bridge 支持版本统一编译为 **0.2.0**,产物收进 `bridge-mod/dist/`,
发布 GitHub Release **`bridge-v0.2.0`**,并更新启动器的下载/发现表。

## 2. 构建矩阵与实际结果

| 变体 | Gradle | JDK | 加载器/映射 | 结果 | 产物大小 |
|---|---|---|---|---|---|
| fabric 1.20.1 | 8.10.2 | 17 | Loom 1.6.11,`BRIDGE_MC_VERSION=1.20.1` | ✅ 成功 | 30,741 B |
| fabric 1.21.1 | 8.10.2 | 21 | Loom 1.6.11,`BRIDGE_MC_VERSION=1.21.1` | ✅ 成功 | 30,663 B |
| forge 1.20.1 | 8.10.2 | 17 | ForgeGradle 6 | ✅ 成功 | 27,466 B |
| forge 1.18.2 | 7.6.4 | 17 | ForgeGradle 5.1,official | ✅ 成功 | 26,287 B |
| forge 1.19.2 | 7.6.4 | 17 | ForgeGradle 5.1,official | ✅ 成功 | 26,425 B |
| forge 1.12.2 | 4.10.3 | 8 | ForgeGradle 2.3,stable_39 | ✅ 成功 | 11,531 B |
| forge 1.16.5 | 7.6.4 | 17 | ForgeGradle 5.1,snapshot | ❌ **失败**(见 §5) | — |
| neoforge 1.21.1 | 8.13 | 21 | ModDevGradle 2.0.91 | ✅ 成功 | 27,619 B |

环境路径:

- JDK 8:`C:\Program Files\Eclipse Adoptium\jdk-8.0.504.1-hotspot`(机器上已有;`.minecraft/runtime/jre-8` 只有 JRE、没有 javac,不能用来编译)
- JDK 17 / 21:`.tmp/jdk/jdk-17.0.20.1+1`、`.tmp/jdk/jdk-21.0.12.1+1`
- Gradle:`.tmp/gradle-dist/gradle-{4.10.3,6.8.3,7.6.4,8.10.2,8.13}`

## 3. 本次修掉的代码缺陷

### 3.1 TCP 通道 socket 竞态(核心 bug)

`handle(Socket)` 里用 try-with-resources 持有连接,但命令是 `server.execute(...)` **异步**在服务器线程跑的:
`handle` 一返回连接就被关闭,结果写到已关闭的 socket → 启动器永远收不到响应,
只显示"命令可能已执行"。**表现就是"AI 说发了指令,游戏没执行"。**

修复:`common/src/main/java/com/agentmc/bridge/LocalBridgeServer.java`
—— 不在 `handle` 里关连接,改由服务器线程任务在 `finally` 里 `flushTo` 之后再 `closeQuietly(client)`。

`forge-1.18.2` **有自己的副本**(它的 `build.gradle.kts` 第 16-17 行把
`LocalBridgeServer.java`/`CommandBridgeSource.java` 从共享源码里排除了),
所以同一 bug 需要在 `forge-1.18.2/src/main/java/com/agentmc/bridge/LocalBridgeServer.java` 单独修一遍。

### 3.2 1.18.2 的指令前导斜杠 bug

1.18.2 那份用 `Commands.performCommand(source, command)`,而启动器发来的指令**带前导 `/`**:
`performCommand` 不认 `/` → 解析失败、**静默什么都不做**(返回 0)。

修复时又发现:**`performPrefixedCommand` 在 1.18.2 根本不存在**(1.19 才加入),
编译报 `找不到符号: 方法 performPrefixedCommand(CommandSourceStack,String)`。
最终写法:自己剥掉 `/`,再用 `performCommand` 并取其返回值判定成功:

```java
String cmd = command.startsWith("/") ? command.substring(1) : command;
int result = server.getCommands().performCommand(source, cmd);
sink.markResult(result > 0);
```

> 1.16.5 / 1.12.2 的 `FileCommandBridge` 早已自己剥掉 `/`(第 41 / 28 行),无此问题。

### 3.3 共享版 `success` 恒为 false(上报 bug)

`Commands.performPrefixedCommand` 返回 **void**(1.21.1 源码 `Commands.java:262` 已核实),
原来执行完既没 `markResult` 也没 `fail` → `CommandBridgeSource.flushTo` 里 `done=false`
→ 响应里 `success` **永远是 false** → 启动器把**执行成功**的指令也报成"⚠️ 命令未执行"。

修复:`common/.../LocalBridgeServer.java` 在正常返回后补 `sink.markResult(true)`
(语法/权限错误会抛 `CommandSyntaxException` 落到 `fail()`,能返回即视为被接受)。

### 3.4 1.16.5 的映射通道写错

`forge-1.16.5/build.gradle` 原为 `mappings channel: 'official'`,
但该变体源码用的是 **MCP 名**(`net.minecraft.command.CommandSource`、
`net.minecraft.entity.player.ServerPlayerEntity`)→ 必须用 `snapshot`:

```groovy
mappings channel: 'snapshot', version: '20210309-1.16.5'
```

### 3.5 NeoForge 1.21.1 接通 0.2.0

新增 `bridge-mod/common-1.21.1/`(由 `common-1.20.1` 移植:`BridgeIO`/`ItemExporter`/
`RconAutoOpener`/`RecipeExporter`,适配 1.21 的 data components 与 `holder.value()`)、
`bridge-mod/neoforge/settings.gradle.kts`(独立根工程)、重写 `neoforge/build.gradle.kts`
(ModDevGradle 2.0.91 / mcVersion 1.21.1 / neoForgeVersion 21.1.250)。

**附带验证**:`common-1.21.1` 同时被 fabric 1.21.1 编译通过,说明移植完整。

## 4. 产物校验(每个 jar 开箱检查,不是看文件名)

在 jar 里直接搜字符串/方法名,确认修复真的进了编译产物:

| jar | mtime | `closeQuietly` | `markResult` | `server_type` |
|---|---|---|---|---|
| fabric-1.20.1-0.2.0 | 10-04 19:52 | ✅ | ✅ | ✅ |
| fabric-1.21.1-0.2.0 | 10-04 19:53 | ✅ | ✅ | ✅ |
| forge-1.18.2-0.2.0 | 10-04 19:54 | ✅ | ✅ | ✅ |
| forge-1.19.2-0.2.0 | 10-04 19:54 | ✅ | ✅ | ✅ |
| forge-1.20.1-0.2.0 | 10-04 19:53 | ✅ | ✅ | ✅ |
| neoforge-1.21.1-0.2.0 | 10-04 19:58 | ✅ | ✅ | ✅ |
| forge-1.12.2-0.2.0 | 10-04 19:12 | —(文件交换,无 TCP 类) | — | —(老协议) |

**踩坑:`clean` 不够,必须 `clean` + 确认 `compileJava` 真的执行过。**
第一次编 1.18.2 时日志显示 `:compileJava UP-TO-DATE`,产出的 jar 里**没有** `closeQuietly`
—— 共享源码改了但增量编译判定为最新。`build_bridge_all.ps1` 因此对每个变体都带 `clean`。

## 5. 未完成:forge-1.16.5

### 现象

```
Could not find net.minecraftforge:forge:1.16.5-36.2.39_mapped_snapshot_20210309-1.16.5.
  Searched in:
    - ...\forge_gradle\bundeled_repo\net\minecraftforge\forge\1.16.5-.../<...>.pom
    - ...\forge_gradle\bundeled_repo\net\minecraftforge\forge\1.16.5-.../<...>.jar
```

关键点:`bundeled_repo` **完全是空的**(所有其它变体都没用它,它们把映射产物放在
`minecraft_user_repo`,解析正常);只有 1.16.5 这条路径要求 `bundeled_repo`。

### 已尝试的办法(全部失败)

1. `clean build` —— 失败(描述符/产物状态不一致)
2. `--rerun-tasks` —— 失败
3. `mappings` 从 `official` 改成 `snapshot 20210309-1.16.5` —— 失败
4. 清掉 `bundeled_repo` / `minecraft_user_repo` 里该版本目录后 `clean build --rerun-tasks`
   —— 失败(重新生成了 `minecraft_user_repo` 里的映射 jar,但仍去 `bundeled_repo` 找)
5. **手工把已生成的映射 jar+pom 拷进它搜索的确切路径** —— 仍然报 Could not find
   (已核对 pom 的 groupId/artifactId/version 与能工作的 1.18.2 完全同构,不是 pom 问题)
6. `--refresh-dependencies` —— 失败
7. **迁移到 ForgeGradle 5.1.+**(与已成功的 1.18.2/1.19.2 同机制) —— 报**完全相同**的错

### 结论

不是插件版本问题,而是**这台机器上 Gradle 对该模块的解析状态已损坏**
(FG4 与 FG5 表现一致)。下一步建议:**换一个干净的 `GRADLE_USER_HOME`** 再编
(可彻底排除损坏缓存;代价是要重新下载 userdev/MCP 产物,约几分钟)。
该方案在本次暂停前**尚未执行**,未产生任何副作用。

### 注意:不要用 dist 里现存的 1.16.5 jar 充数

`dist/agentmc-bridge-forge-1.16.5-0.2.0.jar`(09-01)是**旧源码**构建的:
校验发现其 `AiChat` 里**没有 `permission_level` 字符串**,而当前源码有
(`AiChat.java` 第 55 行 `request.addProperty("permission_level", permissionLevel)`)
→ 它缺少权限上报,不能作为 0.2.0 发布。**1.16.5 必须真正重新编译。**

## 6. 未完成:发布 GitHub Release

`gh` 已登录(账号 `erfanyo`,含 `repo` 权限),具备发布能力。待执行的命令:

```powershell
gh release create bridge-v0.2.0 `
  'bridge-mod\dist\agentmc-bridge-fabric-1.20.1-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-fabric-1.21.1-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-forge-1.12.2-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-forge-1.18.2-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-forge-1.19.2-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-forge-1.20.1-0.2.0.jar' `
  'bridge-mod\dist\agentmc-bridge-neoforge-1.21.1-0.2.0.jar' `
  --title 'bridge-mod 0.2.0' --notes-file <notes>
```

发布后还需更新两处(否则启动器/CI 仍拿旧 jar):

1. `bridge_mod_dist.py` 里的 `BRIDGE_MOD_RELEASES`(新 tag、0.2.0、各 jar 的 sha1)
2. `tools/fetch_bridge_mod_jars.py` 的下载列表

## 7. 重要注意:`dist/` 里有更高版本的旧产物

`bridge_mod_dist` 的发现逻辑**按版本号取最高**,而 `dist/` 现存:

- `agentmc-bridge-forge-1.19.2-0.2.1.jar`、`-0.2.2.jar`(旧构建,**不含 socket 修复**)
- `agentmc-bridge-forge-1.16.5-0.2.1/0.2.2/0.2.3.jar`(旧构建)
- 各 `-0.1.0.jar`

→ 在 1.19.2 上会被解析成 **0.2.2**(而不是刚编好的 0.2.0)。
清理命令(仅删旧产物,不影响 0.2.0):

```powershell
Remove-Item 'bridge-mod\dist\*-0.1.0.jar', 'bridge-mod\dist\*-0.2.1.jar',
            'bridge-mod\dist\*-0.2.2.jar',  'bridge-mod\dist\*-0.2.3.jar'
```

## 8. 复现/重建命令

```powershell
# 全部变体(脚本需 Bypass:本机执行策略禁止运行未签名脚本)
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_bridge_all.ps1

# 只编指定变体(-File 传参时逗号在脚本内拆分)
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_bridge_all.ps1 `
  -Only fabric-1.20.1,fabric-1.21.1,forge-1.20.1
```

脚本会把产物按发布命名复制进 `bridge-mod/dist/`(`fabric` 的默认产物名是
`fabric-0.2.0.jar`,脚本负责改名为 `agentmc-bridge-fabric-<mc>-0.2.0.jar`)。
