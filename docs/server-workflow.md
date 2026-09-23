# 服务端流程：渐进实现

## 第五阶段：客户端实例转换为候选服务端

- 实例详情的“导出”页新增“自动转换为候选服务端”，原有逐文件勾选导出保留为手动兜底。
- `server_pack_rules.py` 只读扫描客户端实例并绑定文件哈希。Fabric 元数据明确声明 `environment=client` 的 Mod 和实例中已禁用的 Mod 才自动排除；Forge/NeoForge 或损坏、未知元数据不能证明适用端时一律保留并写入审核报告。
- 复制 `mods/config/defaultconfigs/kubejs/scripts/datapacks/serverconfig/openloader`；明确跳过 `kubejs/client_scripts`。可选带入一个存档并映射为 `world/`，同时提示其中可能含玩家隐私。
- `server_pack_builder.py` 在隔离临时目录中调用已有的官方安装器流程，静态验证加载器入口后生成完整候选 ZIP。原实例不写入，来源文件在复制前后复核 SHA-256；不携带或生成 `eula=true`，也不启动 Minecraft。
- 候选包包含 `amcl-server-pack.json`、逐文件大小与 SHA-256、机器可读报告和玩家可读审核报告。报告列出每个 Mod 的保留/排除理由、疑似凭据配置的文件名、验证级别和还原方法，不记录绝对来源路径或密钥值。
- 默认可在生成后重新走安全扫描并加入服务端列表；首次启动仍进入现有 EULA 滚动确认，然后由独立服务端托管进程记录本次启动日志。
- 候选服务端导出界面将“保存目录”和“文件名”分开，文件名可省略 `.zip`；默认自动转换包包含已安装并验证的服务端运行库。原逐文件勾选入口明确标为“不含运行库”的手动兜底。
- 服务端“补全运行库”优先直接使用扫描出的 MC、加载器及加载器版本，并自动选择或下载兼容 Java；只有某项无法可靠识别时才询问该缺失项，不再要求用户手动定位 `java.exe`。
- 第一版自动运行库安装限定为 Minecraft 1.17+ 的 Forge / NeoForge。Fabric、原版、旧 Forge 与自动根据崩溃日志迭代修复尚未开放，不能通过猜测启动命令或批量删除 Mod 来绕过。

## Windows 导入收尾修复

- 修复解压后整目录从 `.import-*` 改名到 `server-*` 时可能出现的 WinError 5：现在直接创建唯一的服务端目录，以 `.amcl-importing` 标记未完成状态，不再改名整个目录。
- 文件全部校验后写入元数据，最后移除未完成标记才会显示在列表。失败保留未完成文件并报告路径，不清理原包或已有实例；未完成目录不计入服务端数量。
- 扫描与解压增加进度回调，Qt 层将字节进度归一化以避免超过 2 GiB 时的整数溢出。界面区分扫描、等待确认、解压、登记、完成、取消和失败，不再仅保留模糊的“正在扫描”日志。
- 此变更避免了已报告的整目录改名失败点；不代表绕过了 ACL 或杀毒软件限制，文件写入若仍被拒绝会明确报错并保留现场。
- 已用约 500 MiB、1939 个文件的 Forge 1.19.2 服务端包做过完整隔离导入：扫描、复核、解压、逐文件哈希校验和登记约 27 秒，最终能被列表识别；测试副本随后自动清理，来源包未修改。

## 第四阶段：适用端标签和运行包导出

- `installed_resource_cards.py`：客户端实例 Mod 卡片底部显示适用端标签，使用主题次要文字色，不额外增加卡片高度。Fabric 根据 environment，Forge/NeoForge/多加载器不确定时标未知；工具提示解释双端可加载不代表两端必须安装。
- `server_export.py`：对已验证的 Forge/NeoForge 服务端生成 ZIP，包含 server/libraries、server/mods 中的 JAR 及已验证的平台参数文件；生成 schemaVersion=1 的 amcl-server-pack.json（版本、Java、相对 serverRoot、文件大小和 SHA-256）。不写 startCommand 或绝对本机路径，不沿用来源清单的任意字段。
- 默认且目前仅支持 `runtime-and-mods` 导出模式。明确不导出世界、配置、白名单、日志、server.properties、EULA 或客户端目录。不能作为完整整合包备份，依赖自定义配置的整合包仍需手工整理。重新导入时同样展示此限制。
- 导出不会覆盖已有目标文件。服务端运行或已有后台任务时不允许导出。尚未接入完整配置选择/隐私审查、客户端资料包生成或增量补丁。

注意：文件白名单排除了常见凭据和个人数据文件，但不能判断用户是否把私人内容手工嵌入了 JAR；分发前仍需自行审查授权和包内容。

## 第三阶段：官方运行库补全

- 服务端页“补全运行库”：确认 MC / 加载器版本、所选 Java、官方 Maven URL 后执行。仅支持 MC 1.17+ Forge 和现代 NeoForge。
- `server_install.py` 复用 Java 检测、下载校验和可中断子进程基础能力。官方 SHA-1 无法取得或校验不通过时拒绝执行；不使用包里的安装器或脚本。
- 在临时目录运行官方 `--installServer`，验证启动计划后仅补缺失的 libraries/运行 JAR。同名但不同内容直接拒绝，不替换；合并失败撤回本次新增文件，可能留下空目录。
- 不复制生成的脚本、EULA、世界、server.properties 或安装器日志。安装期间阻止关闭主窗口和启动服务端。
- UI 要求用户自行选择 Java；尚未自动下载 Java。安装器自身联网下载依赖，当前不接管其镜像重试。
- 本阶段只有离线模拟回归，没有完成真实官方下载安装测试。保守参数解析可能拒绝个别加载器版本；失败会提示，不会改为执行脚本。

尚待：旧 Forge/Fabric 自动安装、客户端 Mod 卡片标签、清单与资源包导出、增量补丁、完整真实包联调。

## 第二阶段更新

- `server_launch.py` 从磁盘重建启动计划，支持单个已安装的 Forge/NeoForge 当前平台参数入口；检查依赖文件、限制参数和主类，不传入原始 @文件，不执行脚本。保守子集之外的 JVM 参数会明确拒绝，安装器自动补全仍未完成。
- Java 版本在后台实测；低于已识别最低要求时阻止启动，其余兼容性风险提示确认。启动子进程清除 Java 环境变量中的隐式参数。
- schemaVersion=1 的清单支持相对 serverRoot/clientRoot，拒绝不安全路径与重叠根目录。双目录原样保留，仅服务端根目录用于启动。startCommand 不执行，版本仍从实际加载器入口推断。
- 服务端增加“查看 Mod”；Fabric 环境字段提供客户端/服务端/双端声明，Forge/NeoForge 保守标未知。未接入客户端实例卡片，不自动删除或分发 Mod。
- EULA 读取支持空白与重复键的最终值；首次启动时从 Minecraft 官网加载当前正文，用户必须滑到末尾并明确点击同意，之后才为该服务端原子写入 `eula=true` 与 UTC 时间记录。加载失败、关闭弹窗或未滑到底均不会同意。

依据：[Java 17 参数文件说明](https://docs.oracle.com/en/java/javase/17/docs/specs/man/java.html)、[NeoForge 服务端安装说明](https://docs.neoforged.net/user/docs/server/)。

以下为第一阶段记录；与上述更新冲突时以上述更新为准。

## 已接入

- `archive_inspection.py`：无 GUI 的 ZIP/MRPACK 扫描接口和 CLI。报告包含包 SHA-256、逐文件 SHA-256、大小、包根目录、推测版本/加载器/Java 和脚本列表。错误抛 ValueError；CLI 输出错误 JSON。
- `server_packs.py`：预览后再次校验包哈希，在临时目录解压并逐文件核对，成功后发布至当前 MC 目录的 `servers/server-<id>`。不执行脚本，不解释清单中的命令，不覆盖客户端实例。
- `server_center.py`：扫描、预览、确认、导入、列表、日志、启动和 stop。启动入口与兼容 Java 默认自动识别；首次启动通过可滚动的官方 EULA 确认页收集用户的明确同意。控制台下方提供指令入口。
- `server_host.py` / `server_host_client.py`：服务端由独立后台托管进程运行，AMCL 只通过绑定 `127.0.0.1` 且带随机凭据的控制通道发送指令。关闭启动器不会停服；重新打开后会从 `.amcl-runtime/host.json` 认回当前会话，并读取 `.amcl-runtime/logs/` 中本次启动以来的日志。服务端退出后托管进程随之退出，状态与日志保留供查看。
- `version_home.py`：实例数量旁新增服务端数量页签，切换存储目录时刷新。
- `main.py` / `modpack.py`：常见服务端 ZIP 从整合包入口分流；客户端导入/解压增加安全扫描。

## 现有客户端下载流程与接线位置

1. 下载新实例：`main.start_instance_download` 读取 DownloadTab 选择，经统一下载任务调用 create_instance；该路径仍是客户端路径，不能直接复用为服务端安装。
2. 整合包：`detect_modpack_format` 判断 Modrinth / CurseForge / FTB / flat；`import_modpack` 安装客户端本体及加载器、下载文件，再解压 overrides 和 client-overrides。
3. 服务端应使用独立的安装计划，不下载客户端 assets，不套客户端登录参数；MRPACK 的环境字段与 server-overrides 应在后续服务端导入适配器中处理。

## 未完成（不能视为可用能力）

- Forge/NeoForge 安装器补全、生成并验证平台启动参数；Java 自动选择/下载和版本实测。
- 双目录包的 serverRoot/clientRoot 解析、布局选择；当前不要导入双目录包期待自动启动。
- Mod 客户端/服务端/双端/未知标记，以及依赖校验。缺少元数据时必须标未知，不可猜双端。
- 生成 `amcl-server-pack.json`、脱敏导出、玩家资源包和增量补丁。
- 服务器 Bot 协议接入；完整真实服务端启动测试、GUI 视觉回归。
- 导入任务的取消与统一下载球接入；更多恶意 ZIP 测试（加密位、压缩炸弹、损坏 CRC）。

扫描识别是提示，不是可信签名。ZIP 安全检查不是恶意代码检测；运行 JAR/Mod 仍需用户信任来源。扫描结果不能证明 Mod 两端兼容，也不能证明 Java 正确或服务端启动成功。

## MCSManager 兼容（导出 + 联动）

AMCL 管理的服务端目录（`servers/server-<id>/`）本身就是标准 MC 服务端布局，可直接导入
[MCSManager](https://mcsmanager.com/) 的"导入已有实例"功能。

**兼容契约**（已实现）：

1. **标准目录结构**：`mods/` / `config/` / `libraries/` / `server.jar`（或加载器入口）
   / `eula.txt` / `server.properties` — 与 MCSManager 期望一致。
2. **私有状态只进边车**：AMCL 元数据只存 `.amcl-runtime/` 和 `amcl-server-pack.json`；
   MCSManager 忽略未知文件，互不干扰。
3. **启动命令可导出**：`aml server export-cmd <root>` 输出纯 `java ...` 命令行，
   可直接填入 MCSManager 的"启动命令"字段。
4. **自包含启动脚本**：`aml server setup-start <root>` 在服务端目录生成
   `start.bat`（Windows）/ `start.sh`（Linux），目录自包含后可直接导入面板。

**导入步骤**：

```bash
# 1. 先在服务端目录生成启动脚本（自动选 Java）
aml server setup-start servers/server-abc123

# 2. MCSManager → 实例管理 → 导入已有实例
#    目录: servers/server-abc123 的绝对路径
#    启动命令: start.bat（或直接粘贴 aml server export-cmd 输出的命令）
```

**不嵌入 MCSManager**：AMCL 的定位是本地桌面启动器 + 无头服务端管理器，差异化在 AI
（客户端实例→服务端转换、NL→server.properties 生成、崩溃诊断、Mod 两端兼容判断）。
MCSManager 的远程/多节点/Web 面板/Docker 守护是它的强项，两者互补而非替代。

**MCSManager API 适配**（opt-in，待做）：设置里填 MCSManager 地址 + API Key →
AMCL 内可列/启停/看日志/发指令。用现成 [`mcsmapi`](https://github.com/sokoko-org/mcsmapi) 包起步。
