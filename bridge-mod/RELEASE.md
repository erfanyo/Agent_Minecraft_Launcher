# AgentMC Bridge — 发布说明(RELEASE)

## 当前支持矩阵(2026-09 目标；未构建不等于已发布)

| 平台 | MC 版本 | 状态 |
|---|---|---|
| Fabric | 1.21.1 | ✅ 已编译(产物 `dist/agentmc-bridge-fabric-1.21.1-0.1.0.jar`) |
| NeoForge | 1.21.1 | ⏳ 待重新核验/发布 |
| Forge | 1.20.1 | ✅ 已构建验证（`forge/build/libs/agentmc-bridge-forge-1.20.1-0.2.0.jar`） |
| Forge（优先）/ Fabric | 1.19.2、1.18.2 | ⏳ 目标版本，按 Forge → Fabric 顺序构建 |
| Forge | 1.16.5、1.12.2、1.7.10 | ⏳ 目标版本，独立 JDK 8 旧版兼容实现 |

> 版本稳定前只在 GitHub 发布源码与编译产物,**暂不**上传 Modrinth、暂不打进启动器 exe。

## GitHub 发布步骤

1. 仓库:`erfanyo/Agent_Minecraft_Launcher`(bridge-mod 作为子目录在仓库里)
   push 源码(git add bridge-mod + 其余,或单独管理)
2. 发布 Release(如 tag `v0.1.0`),上传这些文件:
   ```
   bridge-mod/dist/agentmc-bridge-fabric-1.21.1-0.1.0.jar   ← 编译产物(可用)
   ```
3. 下载 URL 已按此仓库填好(tag = `v0.1.0`,语义化版本规范):
   `https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/v0.1.0/agentmc-bridge-fabric-1.21.1-0.1.0.jar`
   > tag 命名规则:语义化版本 `v<主>.<次>.<补丁>`,预发布加后缀如 `v0.1.0-alpha`。
   > 平台/版本信息放资产文件名(如 ...-fabric-1.21.1-0.1.0.jar),不放 tag。

## 编译产物怎么生成

```
set JAVA_HOME=C:\Users\erfanyo\AppData\Roaming\.minecraft\runtime\java-runtime-delta
set GRADLE_USER_HOME=E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-home
E:\Agent_Minecraft_Launcher 0.0.1\.tmp\gradle-dist\gradle-8.10.2\bin\gradle.bat -p bridge-mod :fabric:build --no-daemon
copy bridge-mod\fabric\build\libs\fabric-0.1.0.jar dist\agentmc-bridge-fabric-1.21.1-0.1.0.jar
```
(详见 README「构建」;Gradle 必须 8.10.x)

## 版本表(启动器自动拉取用)

启动器 `bridge_mod_dist.py` 内置表:
```python
BRIDGE_MOD_RELEASES = {
    "fabric": {
        "1.21.1": {"version": "0.1.0",
                   "url": "https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/download/Alpha/agentmc-bridge-fabric-1.21.1-0.1.0.jar",
                   "sha1": "2cec62a209a6285e577fecb0497d6e53204ebbd4"},
    },
}
```
每次迭代:编译 → 更新 dist jar → 发新 Release(注意 tag)→ 更新启动器版本表(版本号/url/sha1)。
