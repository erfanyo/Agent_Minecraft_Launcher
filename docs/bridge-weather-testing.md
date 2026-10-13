# BridgeMod 确定性天气测试

此测试不调用模型：在游戏中输入 `/ai 天气改为雨天`，脚本读取真实桥接请求，以该玩家身份执行固定的 `weather rain`，再将执行结果写回 AI 回复。用于检查请求、权限、命令执行和结果返回链路。通过这一用例不代表所有指令、加载器或模型均已通过测试。

## 脚本回归测试

```powershell
.venv\Scripts\python.exe -m unittest test_bridge_weather_script -v
```

覆盖 TCP 和旧版文件传输、允许/拒绝执行、请求序号、命令匹配、过期请求以及禁止控制台身份。模拟桥接测试不启动游戏。

## 自动真实游戏测试（Windows）

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-bridge-test.txt
.venv\Scripts\python.exe tools/bridge_weather_game.py --instance .minecraft/versions/fabric-loader-0.19.5-1.21.1 --world "新的世界" --jar bridge-mod/dist/agentmc-bridge-fabric-1.21.1-0.2.0.jar --case both
```

需要已安装的目标实例、对应 Java、可读取的单人存档和桌面会话。现代版本使用快速进入世界参数，旧版 Forge 通过测试窗口的菜单进入唯一的隔离世界。测试会短暂切换前台到它自己的游戏窗口。桥接端口 26100 必须空闲。

可用 `--world-source` 指定只读的模板存档；只向新版本升级，不要把新版本存档用于旧版。矩阵脚本为 1.12.2 创建独立的旧版世界元数据，1.18.2 和 1.20.1 使用 1.16.5 世界副本。

批量重跑八个目标（每个目标均有允许和拒绝两项）：

```powershell
.venv\Scripts\python.exe tools/bridge_weather_matrix.py
```

使用 `--targets forge-1.19.2 neoforge-1.21.1` 可只跑指定目标；结果逐项保存到 `.tmp/bridge-matrix-report.json`。矩阵中的实例名对应当前工作区，其他机器需调整 `TARGETS`。缺少实例会记录失败，不会偷偷跳过。

程序复制存档到 `.tmp/bridge-weather-*`，仅加载指定桥接 JAR，以离线测试账号运行，分别开启和关闭作弊权限。原存档不改动，依赖和原生库缓存复用已有安装；`地下酒吧` 被明确排除。测试结束正常关闭自己的游戏进程，读取保存后的 `level.dat` 验证天气。若被迫结束进程或退出码非零，该用例失败。

每个测试目录保存 `report.json`、`client-output.log` 和 Minecraft 日志。自动执行流程不创建 Qt 截图应用，以免中途改变 DPI 状态干扰旧版菜单坐标。先前留下的截图仅作辅助，不参与通过判定。报告不会记录桥接令牌。

## 手动进入世界 / 其他加载器

先进入专用单人世界，停用启动器的游戏内 AI 响应，防止两个响应器同时回复。启动以下脚本后在游戏输入测试指令：

```powershell
.venv\Scripts\python.exe tools/bridge_weather_test.py --bridge-dir "实际世界运行目录/.bridge" --expect success --report .tmp/bridge-weather-result.json
```

无作弊权限的世界使用 `--expect denied`。脚本自动识别 TCP 或旧版文件协议，也可用 `--transport tcp|file` 指定。独立响应脚本检查命令结果和回复被模组消费，不检查世界保存数据，需另行观察天气。

## 2026-10-13 实测

- 脚本回归：7 项通过。
- Fabric 1.21.1 / Loader 0.19.5：允许权限用例通过，保存后确实下雨；权限 0 用例通过，命令被拒绝，保存后没有下雨。两次游戏正常退出。
- 记录：`.tmp/bridge-weather-3244487d/report.json` 和 `.tmp/bridge-weather-7ab1f8fb/report.json`。
- 最终脚本再次复测两项通过：`.tmp/bridge-weather-92cf68b3/report.json` 和 `.tmp/bridge-weather-1a676321/report.json`。
- 修复：以玩家身份执行时原先继承了控制台权限；现在创建玩家自己的命令源。新版本根据执行回调判断成功，避免命令被拒绝时误报成功。
- 加载器构建验证与真实游戏验证分开记录，未实际运行的版本不能视为游戏测试通过。
- 八个目标构建均通过：Fabric 1.20.1 / 1.21.1，Forge 1.12.2 / 1.16.5 / 1.18.2 / 1.19.2 / 1.20.1，NeoForge 1.21.1。产物位于 `bridge-mod/dist`，ZIP、SHA256 和清单已同步更新。
- 启动器回归：748 项，747 通过、1 跳过，记录位于 `.tmp/bridge-weather-regression.log`。

## 扩大范围后的结果（2026-10-13）

| 加载器 | Minecraft 版本 | 允许 / 拒绝权限 |
| --- | --- | --- |
| Fabric | 1.20.1、1.21.1 | 全部通过 |
| Forge | 1.12.2、1.16.5、1.18.2、1.19.2、1.20.1 | 全部通过 |
| NeoForge | 1.21.1 | 全部通过 |

共 16 项真实游戏用例，通过命令结果、回复消费和保存后的天气状态三项检查，全部正常退出，退出码为 0。汇总：`.tmp/bridge-expanded-report.json`。汇总逐项核对 JAR 的 SHA256，确认测试的是当前分发产物；合集和校验文件已更新。

自动回归新增至 19 项（协议 15、世界隔离 3、旧版参数 1）；完整启动器回归 760 项，759 通过、1 跳过。最终日志：`.tmp/bridge-expanded-unit.log`、`.tmp/bridge-expanded-regression-final.log`。

本轮发现并修复：

- 旧版 `minecraftArguments` 先替换再拆分，导致含空格目录被截断。现在先拆分模板，再替换每个参数，带空格路径和账号名保留为一个参数。
- Forge 1.12.2 关闭作弊时，Minecraft 连权限等级 0 的 `/ai` 也拒绝。对话入口现在公开，实际天气命令继续使用玩家权限，拒绝用例验证不会绕过权限。
- 测试框架：旧版进入世界后的等待、1.12.2 保存退出菜单和系统关闭窗口、避免截图组件在执行中改变 DPI 状态。

旧版请求中 `permission_level` 可能把集成房主标为 4；权限拒绝的判定依据是 Minecraft 实际执行结果和保存的天气状态，而不是该字段。

初次异常的 1.12.2 启动曾将目录截断为 `E:\Agent_Minecraft_Launcher`，相关测试进程已结束；未自动删除这个工作区以外的目录。前面的失败测试目录与日志保留用于排查。

尚未覆盖：Linux/macOS 真实游戏、专用服务端和多人权限、其他指令、与大型模组包共存。随后发布准备已修正 1.12.2 的 `@VERSION@` 注解并重新编译；仅版本注解变化，原始功能测试报告保留测试时的哈希。预编译清单及注解另有发布输入回归验证。
