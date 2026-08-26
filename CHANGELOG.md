# 更新日志(CHANGELOG)

本启动器采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。
版本号遵循语义化版本:[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

> ⚠️ **发版要求(2026-08-24 定)**:打包/发布时更新日志出**两版**——
> ① 本文件 = **完整技术版**(给开发者,条目细、含模块/commit 信息);
> ② 另出「摘要」版(名义上是摘要,实际要求**新手能看懂**):大白话讲"这次更新能干嘛、对用户有啥用",
> 不堆技术黑话,面向普通玩家/朋友。Release / README 面向用户用摘要版,面向开发者用技术版。

> 说明:早期开发历史在本地重装系统时丢失,故 v0.2.0 起汇总记录全部已实现功能,
> 后续版本只记录增量。

## [v0.4.2] - 2026-08-26

> 🐛 补丁版:修复 v0.4.1 引入的引导页/引导教程显示问题。

### 🐛 修复
- **首次启动引导页深色系统下「黑底黑字」**(`onboarding.py`):v0.4.1 给 `OnboardingDialog` 加了
  `QDialog#onboarding_dialog { background: rgba(...) }` 样式表——Qt 中父控件一旦设置样式表,引擎接管
  渲染,子控件(QLabel/QRadioButton/QLineEdit 等)文字回退为默认黑色,且半透明 rgba 背景被画成黑块;
  改为**不透明**深浅自适应背景 + 样式表内对 QLabel/QRadioButton/QGroupBox/QLineEdit/QComboBox/
  QCheckBox/QSpinBox **全部显式上色**(`text_color()`),标题/footer 同步补色。已按深/浅色渲染采样验证。
- **引导教程遮罩与路由不同步**(讲「加载器」时启动器还停在「版本」页,`ui_route.py`):`loader_panel`
  是 `DownloadTab` 内部 QStackedWidget 的第 1 页,但 `_auto_switch_container` 只认**有 `switch_to()`
  方法的容器**(ResourceCenter/CenterShell),`DownloadTab` 只有 `menu`+`stack` → 内部堆叠页未切,
  遮罩框在隐藏页上;改为**沿 parent 链把所有 QStackedWidget 切到「包含目标控件」的页**(优先容器
  `switch_to()` → 其次 `menu.setCurrentRow()` 同步高亮 → 兜底 `setCurrentIndex`),并补 `QStackedWidget` 导入。
- **教程气泡跑出窗口**(`guide_overlay.py`):气泡翻到上方时 `by = tr.top()-H-18` 无下限 clamp(目标贴顶
  即出窗)、宽度固定 300 不随窗口缩、高度按字符数估算不准(中文易溢出);改为**宽度自适应窗口** +
  `QFontMetrics.boundingRect` **精确排版高度** + 上下/水平全部 clamp 进窗口(上放不下且下无空间 → 窗口底部安全区)。
- **FlowLayout 页面切换偶发崩溃**(`resource_center.py`):`_do_layout` 遍历 item 时可能碰到已删除的
  QWidgetItem(PySide6 双所有权经典坑)抛 `RuntimeError`;加 try/except 防御,跳过失效 item 并从列表移除。

### ⚠️ 已知问题(待正式版处理)
- **微软正版登录报 `AADSTS700016`**(`microsoft_auth.py`):点「微软正版登录」弹 `HTTP 400` /
  `unauthorized_client` / `Application with identifier '00000000402b5328' was not found in the directory …`。
  **根因(已实测)**:v0.4.1 沿用的 Mojang 公开 client_id `00000000402b5328`(及 azalea/社区的
  `00000000441cc96b`)+ `/consumers` 端点,均已不在消费租户 `9188040d-6c67-4c5c-b112-36a304b66dad` 中;
  `/common`、`/organizations` 分别报 no-tenant / multiple-resource。→ 微软已回收这些 Minecraft 公开
  client_id 在该租户的可用性(2025 后对第三方启动器收紧,要求**自注册 Azure AD 应用**,见 PrismLauncher #3300 等)。
  **解决方案(需一次性手工注册,待定)**:Azure portal 免费注册个人 Azure AD 应用取自己的 `client_id`
  (允许 device code,scope `service::user.auth.xboxlive.com::MSCS`),替换 `_CLIENT_ID`;规划做成「设置里可填
  自定义 client_id」最稳妥。详见 `ROADMAP.md` 待办。

## [v0.4.1] - 2026-08-26

> 📄 正式版预览(测试版)。用户向说明见 `RELEASE_NOTES_0.4.1.md`。

### 🔐 微软正版登录
- 新增 `microsoft_auth.py`:**微软 OAuth 设备码流 + 令牌链**(微软→Xbox Live→XSTS→Minecraft)+
  `entitlements/mcstore` 所有权校验 + `minecraft/profile` 取账号名/UUID;用公开 client_id。
- 登录卡片:`更改登录方式 ▾` 里可点「**微软正版登录**」——弹窗给 device code + 网址并自动开浏览器;
  后台轮询授权,成功后存凭证并显示「微软正版 · 已登录」。支持「退出正版登录(回离线)」。
- **启动接入**:正版用**账号真实 UUID + MC 访问令牌 + user_type=msa**(online 服能过验证);离线用
  **离线 v3 UUID**(md5 OfflinePlayer:姓名,不再每次随机,存档稳定)+ legacy。
- **自动刷新令牌**:每次启动用 refresh_token 换新令牌(免重登);失败自动回退已存令牌。
- **皮肤头像**:登录后拉真实 3D 头像(crafatar),缓存到 AMCL/cache/avatars,失败回退占位。
- 配置:`login_method`(offline/microsoft)+ `ms_credentials`(仅存本机)。

### 📦 整合包导出 · Modrinth `.mrpack` 哈希回填
- 导出向导可选「Modrinth .mrpack(推荐)」/「扁平 .zip」。
- **哈希回填**:mods/ 里的 jar 按 sha1 查 Modrinth,匹配到 → 放进 `files[]`(导入时走 Modrinth 下载 +
  收集 required 依赖);匹配不到(本地/非 Modrinth)或非 mods/ 文件 → `overrides/`。
- `modrinth.index.json` 的 `dependencies` 自动写 `minecraft` + 加载器版本(从实例推断)。

### 🖥 实例详情 · 新页签(参考菜单)
- 新增「**概览**」(实例信息 + 一键启动/打开目录)、「**设置**」(单实例启动内存,存 launch_options.json)、
  「**导出**」(整合包导出向导)、「**投影原理图**」(检测到 机械动力/Create 时出现,与 TACZ 枪包同款方案)。
- 设置-界面移除老版「新手教程(基础版)」入口,仅保留新版「重播引导教程」。

## [v0.4.0] - 2026-08-26

> 📄 用户向摘要版见 `RELEASE_NOTES_0.4.0.md`(面向玩家/朋友的大白话版本)。

### 🛠 崩溃诊断 · 自主修复回路(进阶②)
- 新增技能「崩溃诊断·自主修复回路」(进阶、默认关):AI 诊断出崩溃原因后,对**可自动修复项**
  (内存不够→`set_setting` 加内存 / 冲突/损坏 Mod→`install_mod` 重装兼容版 / 实例乱→先备份再建新实例)
  在**用户同意 + 工作区可写**时**直接动手并验证**;改不了的(显卡驱动/硬件/需删存档)明确说明,不硬来。
- 铁律:写操作前先经用户同意 + 确认有「工作区可写」权限;动手前先 `backup_instance` 备份;
  **绝不删除/覆盖用户存档、世界、配置**;同一修复项最多试 1~2 次,失败停并回退到修改意见清单/云端深度诊断。
- 配套:云端工具挂载新增 `crashrepair` 组(崩溃/诊断/修复关键词命中→挂上 install_mod/install_mods/
  set_setting/backup_instance/install_instance 写工具),`CLOUD_MAX_TOOLS` 10→14;工具执行器仍按
  `ai_actions` 校验(readonly 拒写 / workspace_write 放行,已实测)。

### 🧩 bridge-mod 支持扩展
- **forge 1.20.1**:bridge-mod 在 Forge 1.20.1(47.1.3)下**编译+实测通过**(方案B:仅指令口+/ai;
  ModDevGradle `legacyforge` 插件)。`mods.toml` 修正为 Forge 格式(`javafml` / `loaderVersion [47,)`)。
- **bridge-mod 自动发现(以后发新版免改启动器)**:`bridge_mod_dist.py` 改为**按文件名模式自动发现**
  jar(`agentmc-bridge-{loader}-{mc}-{ver}.jar`),顺序为 离线内置(_MEIPASS) → 本地 `bridge-mod/dist` →
  GitHub Releases(在线按名字匹配)→ 版本表兜底(仅作 sha1 兜底)。新版本/新加载器/新 MC 版本
  只要发布 jar(或丢进 dist)即可识别,**无需改本文件**。
- **一键配置明确化**:版本兼容 → 自动下载安装;不兼容 → 明确提示"暂不兼容",并引导可改走 RCON 临时方案;
  自动兜底(自动选择)在 bridge-mod 不兼容时会提示原因再走 RCON。
- **`check_bridge_mod` 接入一键配置(版本更新检测)**:一键配置 bridge-mod 现在区分
  `not_installed / outdated / up_to_date` 三态——已装且最新 → 提示就绪;**已装但版本旧 → 提示"可更新到最新",一键覆盖旧 jar**;
  未装 → 下载。三个入口(专用 bridge / 自动选择)统一走这套检测,不再只要"装了 bridge jar 就当作就绪"。
- **RCON 自动开启反射修正(`RconAutoOpener`)**:原反射找 `create(MinecraftServer,String)` /
  `create(ServerInterface,String,int)` 签名,但 Forge 1.20.1 下工厂是**单参**
  `RconThread.create(ServerInterface)`(srg `m_11615_`;生产运行时为 srg 名),且只有 `DedicatedServer`
  implements `ServerInterface`。实测确认:**专用服务器 vanilla 已自行开 RCON**(enable-rcon=true 时
  `DedicatedServer.initServer()` 调 `RconThread.m_11615_(ServerInterface)`,日志 "RCON running")。
  故修正为:专用服务器 → 识别 vanilla 已管理并跳过(不再误报 "signature not found" / 重复开启端口占用);
  非专用(单人集成,1.20.1 不是 ServerInterface)→ 记日志跳过。主通道仍为本地指令口(TCP 26100)。
- **离线通道取 jar bug 修复**:内置 `_MEIPASS/bridge-mod/` 通道原来把 Forge 误判成 fabric 去匹配
  (`want = "neoforge" if neoforge else "fabric"`),导致 Forge 实例离线通道找不到 jar;改为按实际 loader 匹配。
- **jar 资源包元数据**:补 `pack.mcmeta`(1.20.1 = pack_format 15;1.21.1 NeoForge = 18),
  消除客户端 "Missing metadata in pack / failed to load a valid ResourcePackInfo" 告警/报错。
- **实测**:Forge 1.20.1 服务端启动后 mod 正常加载;BridgeCore 启动本地指令口(TCP :26100)+ token.txt
  + items/recipes 导出;经 TCP 发 `weather rain` 写 command_result.json、发 `/ai` 写 ai_request.json,
  写入 ai_reply.json 后回显 `[AI] …` 且被消费。
- **游戏内 AI 端到端验证**:启动器侧 `in_game_ai.py`(`InGameAI` 轮询 + `make_answerer` 按 `ai_in_game`
  路由、强制挂指令工具)离屏实测通过 —— ai_request.json → answer_fn → ai_reply.json round-trip 正确,带 instance 上下文。

### 🔄 实例列表「实例(共x个)」自动刷新
- 用 `QFileSystemWatcher` 监听 `versions/` 目录:子文件夹**新增/删除**(外部放的实例、导入的整合包、
  删除的实例)→ 防抖后自动刷新实例列表与「实例(共x个)」计数,无需手动点刷新/切页。
- 防抖(500ms)合并连续变动;`_tidy_base_versions` 迁移只做一次,不触发自身死循环;
  切换游戏目录后重建监听指向新 `versions/`。
- 实测:temp 目录下新建实例目录 → 计数 0→1 自动刷新;删除 → 1→0。

### 🌙 深色模式修复(实例详情 / 更新日志)
- **实例详情 · Mod 列表**:Mod 项文字原本硬编码黑色(`Qt.GlobalColor.black`),深色模式下看不清;
  改为用主题文字色(`text_color()` 启用 / `muted_color()` 禁用),列表套用 `list_style()` 深色适配。
- **更新日志**:`changelog_html()` 原先 `<li>`/body 颜色硬编码(黑/#888888),深色模式下正文黑字;
  改为颜色取自 `ui_style.current_color()`(text/muted/accent),深浅色/自定义主题自适应;
  「正在拉取/拉取失败」提示也改用 `muted_color()`。
- 数据包/光影包列表(instance_manager `_dir_list_widget`)同样套用 `list_style()` 深色适配。

### 🎨 图标系统:emoji → 主题化单色 SVG(灵感 #17 第一批)
- 新增 `theme_icon.py` + `icons/*.svg`:**单色线框图标,渲染后按 `current_color('accent')` 染色**,
  深浅色 / 自定义主题 / 色盲模板 下图标颜色自动跟随,风格统一、极简。
  内置兜底(内嵌 SVG 表),打包后仍可用;`icons/` 文件优先(易编辑)。
- 接入点:`LeftMenu.add_item(label, icon)` 支持**主题图标名**(渲染成 QIcon,不再污染文字);
  下载新资源左侧菜单 8 项(首页/实例/整合包/Mod/光影/数据/资源/插件)已换用主题图标,去掉 emoji。
- 主题刷新联动:换色时 `recolor_icons()` 清缓存,图标立即用新配色;PyInstaller spec 加 `icons/*.svg` 打包。
- 说明:文字内容里的 emoji(资源科普、AI 系统提示等)属内容文本,不是 UI 图标,本批不强制替换。

### 🔧 加载器卡片按版本显隐(下载新资源)
- 选版本后**异步检测各加载器是否有可用版本**,再决定显示哪些卡片:不可用的直接隐藏,
  不再"先显示 4 张再收起"。切换版本先从无残留再按可用性回填。
  (例:1.20.1 隐藏 NeoForge 卡片、显示 Forge;1.21.1 隐藏 Forge、显示 NeoForge)

## [v0.3.0] - 2026-08-24

### 🧠 AI 助手(本地模型全链路)
- **内置本地模型**:设置新增「内置本地模型」provider(免费离线,grammar 约束工具调用);
  首次用到自动下载(镜像优先)+进度弹窗+状态徽标(未下载/下载中/已就绪/推理中)+**冷启动预热**
- 多模态按模型能力自动联动(local_builtin 关 / openrouter 开,可手动覆盖);`ai_in_game` 三档
  (off/cloud/local)+ 游戏启动卸载/保留联动;窗口关闭卸载无残留 llama-server
- **AI 策略三档**(设置页 + AI 面板快捷切换):本地优先(默认,本地模型先评审复杂度,
  简单自己做/难交云端)/ 云端优先 / 混合——判定自由度还给模型
- 任务路由优化:规则引擎收敛(FAQ 精确化+置信度分级+追问降级+顺序修正)+ **本地模型评审器**
  `route_by_model`(31 条测试集判定 100% vs 关键词表 31%)
- **云端稳定性**:请求超时拆分(连接 15s/读取 180s)+ 配置检查 + 友好错误提示
  (Key 无效/余额不足/模型名不存在/限流/网络);修复 worker 跨线程 Qt 原生崩溃(0x8)
- **云端 token 优化**:工具按需挂载(每轮输入 -63%)+ max_tokens 限长 + 结构利于 DeepSeek 前缀缓存
- AI 面板:策略快捷切换按钮;未选模型时隐藏发送/自测;输出语言跟随界面;长回答首行摘要+展开
- 新增「bridge-mod 指南」技能:AI 认知内置私有 Mod(用途/支持范围/装法/测试阶段)
- 新增「**非主流 Mod 兼容性检查**」技能:提醒 AI 判断某 Mod 在某加载器有没有时,先查"同名跨加载器非官方版"
  (如 Fabric 的 `voxy` 有 GitHub 上非官方的 NeoForge 版)+ "Fabric mod 被转译到 Forge/NeoForge、把
  `fabric-api` 换成 Forge 等价物"的可能+ "**选装/需自行编译**的资源(如本整合包里的 `voxy` 为选装、需跑编译脚本,"
  "缺失≠装漏)"——别急着下结论"没有/缺 fabric-api/缺失依赖"。

### 🔤 Mod 描述翻译(本地 AI)
- 93 条 MC 标准译名术语表 + 本地翻译引擎(复用 chat 通道,temp 0.1)
- 翻译缓存绑定模型指纹(版本变更整批作废)+ 置信度标记 + 失败优雅降级 + 懒加载复用 llama-server
- 资源中心 Mod 详情显示中文翻译 + "机翻仅供参考" + 设置开关(`ai_mod_translate`)
- 游戏内 AI 翻译方案已定(场景 C:`/amc` 命令 → bridge 协议扩展 → tellraw 回显,待 bridge v0.2.0)

### 🧪 配方旁路(无需进游戏查配方)
- 直接读实例 mod jar / 原版版本 jar 里的 datapack 配方:已装 mod 不用进世界就能查配方
- 与 bridge 导出合并:jar 数据为基座,bridge 数据为"实际生效"覆盖;特殊配方
  (Mekanism 冶金灌注等)的原料未导出缺口由 jar 旁路补上
- 解析缓存落 `AMCL/cache/recipes-jar/`(带签名自动失效,不散落用户目录)

### ⚙️ 设置与镜像
- 设置对话框按功能拆成标签页:游戏 / 界面 / AI 助手 / 镜像源
- 下载镜像策略四档:官方优先(慢/失败换镜像) / 镜像优先 / 只用官方 / 只用镜像;
  支持自定义镜像站增删,旧配置自动迁移
- AI 设置拆分云端/本地两大块,「当前使用(AI 策略)」统一三档;帮助菜单并入设置

### 📦 便携与打包
- AI 相关文件(模型/运行时/缓存)统一收进 `AMCL/`(AI规划 §11)
- **exe 内置 llama-cpp 运行时 + bridge-mod jar**(离线通道,首次运行自动复制到 AMCL)
- 更新日志改从 GitHub 拉取(异步+刷新+失败重试)

### 🎨 界面与体验
- 模型徽标简化(☁ 云端/🖥 本地 + 悬停详情);登录卡片头像小窗自适应缩放
- 设置页长内容滚轮;「一键配置 ▾」(bridge-mod/RCON)入口恢复至首页
- 下载进度统一入口:点圆环 → 下载详情可见 AI 下载 / 模型下载进度
- **界面模式改叫「全面 / 摘要」**(原"新手/专家"显得看不起新手):设置→界面可切;全面=显示资源科普/详细提示,摘要=隐藏精简;内部值仍兼容旧配置
- **「下载新资源 → 实例」页新增「导入整合包(.mrpack / .zip)…」按钮**:已有整合包文件(Modrinth/CurseForge/实例文件夹 zip)不用先去配游戏版本/加载器,直接选文件导入成新实例(复用文件菜单的完整导入流程)
- **「下载新资源」新增「🎁 整合包」分类页**(像 Mod 一样浏览 Modrinth 整合包):搜索/排序/标签筛选/改加载器过滤,显示封面+描述(中文翻译)+作者+下载数+版本选择;点「下载」自动下载 `.mrpack` 并作为**新实例**导入(自动装基础+加载器+全部 mod),无需先选目标实例。左侧菜单、首页卡片同步新增「整合包」入口。
- **资源中心标签筛选改成「多级菜单」**:原来"手输标签(逗号分隔)"改为点开后按**分组子菜单**勾选(如 Mod:玩法/内容/功能/性能;光影:特性/风格/性能影响;资源包:分辨率/特性/风格;整合包:玩法/内容/性能),可多选(选中项在按钮上显示数量,OR 并集过滤);数据包在 Modrinth 无分类,按钮禁用显示"无标签"。
- **📖 新手教程(基础版,模块化,已临时弃用)**:灵感 #7 第①部分启动器教程曾落地(内容数据 `tutorial_content.py` + 通用渲染器 `tutorial_gui.py`,与 UI 解耦;按页面讲"每个控件在哪、有什么用":基本概念(实例 vs 版本)/ 我的版本 / 下载新资源 / 实例管理 / 设置 / AI 面板 / FAQ)。**但效果不够好 → 2026-08-25 临时弃用**:隐藏主入口(帮助菜单 + 首页按钮),改做**引导式教程**(箭头+文本指着真实 UI 引导);现于 **设置 → 界面 →「已临时弃用 / 废案(未移除)功能」** 登记,只保留"临时查看"入口(新增 `deprecated_features.py` 登记表,以后弃用的前端功能都登记到这里)。
- **🧭 引导式教程框架(演示,UI 路由方案)(2026-08-25)**:不再用静态说明页,改为**指着真实 UI 引导**。通用框架:`ui_route.py`(逻辑 route → 真实控件解析)+ `guide_overlay.py`(spotlight 遮罩:调暗其余、目标控件挖洞高亮、箭头+说明气泡+上一步/下一步/跳过)。步骤=纯数据 {route, arrow, text};UI 改了只改 route,框架不动。入口:菜单「帮助 → 📖 引导教程(演示)…」,demo 指向 **启动实例(启动游戏)** → 启动器设置 → 下载新资源/Mod。
- **实例管理 → 实例详情**:对话框标题与"管理实例"入口文本统一改为「实例详情」(与后续"和下载新资源一致的左菜单+右面板"布局方向一致,当前仍为对话框)。
- **设置改为顶部标签卡 + 统一布局(模块化)**:设置入口不再弹**模态**对话框,改为主窗口「设置」标签页(和「我的版本 / 下载新资源」平级)。新建 **`CenterShell`**(左菜单纵向 + 右面板,和下载新资源同款操作逻辑)+ **`SettingsCenter`**(左菜单:游戏/界面/AI 助手/镜像源 → 右面板;底部「保存设置」)。这解决了引导遮罩被模态设置框挡住的问题(设置变非模态)。`open_settings` 改为切换到「设置」标签卡(镜像源… 会切到镜像源小节)。
- **🧭 引导式教程方案已记录**:`引导式教程-方案.md`(技术方案 + 不确定清单,防上下文丢失;不确定处标 ⚠️,做对应部分时再问)。`ui_route`(route→控件)+ `guide_overlay`(spotlight 遮罩+气泡+上一步/下一步)框架 + 演示先落地。
- **左菜单独立模块 + 统一布局(模块化,为动画预留)**:新增 **`left_menu.py`(LeftMenu 独立模块)**——"左菜单"抽成独立小模块,样式统一、可选中高亮(蓝条+圆角),去掉折叠功能,内部可后续加动画。`CenterShell`(设置/实例详情/下载新资源共用)与 **ResourceCenter** 都改用它;删除原 ResourceCenter 的"◀ 收起/▶ 展开"折叠按钮。
- **深色模式统一(实例详情等对话框)**:新增全局深色调色板 `apply_global_dark_palette`(系统深色时应用,默认控件 QMenu/QComboBox/QTabWidget/QMessageBox 等不再露浅色)+ 对话框深色样式 `dialog_dark_style`;实例详情标签页改用 `tab_style`(和「我的版本」一致),恢复其内部大量"没兼容深色"的菜单/按钮/列表。**实例详情改为"左菜单 + 右面板"布局**(复用 CenterShell,和下载新资源/设置同一套)。
- **配色主题架构预留(未来自定义配色方案)**:所有颜色集中到 `ui_style.COLOR_SLOTS`(颜色槽),样式函数经 `current_color(name)` 读取;自定义主题 = `set_custom_colors({name: color})` 覆盖某颜色槽即全局生效。预留设置键 `ui_theme`(auto/dark/light/custom)与 `ui_custom_colors`(dict),启动时 `load_theme_from_settings` 接入(设置界面暂未做入口)。
- **实例详情改为标签页(位于「我的版本」右边)+ 出现动画**:未选实例时**隐藏**「实例详情」标签页;在「我的版本」选中一个实例后,它**出现在「我的版本」右边**(该标签右侧的"下载新资源"等标签右移腾出空隙),带**淡入+上浮**动画(重排由 QTabWidget 完成);取消选中/无实例即隐藏。`实例详情`由模态对话框改为**可复用标签页**(`InstanceManagerDialog` 改为 QWidget,支持 `set_instance`),右键"实例详情…"也改为切到该标签页。
- **移除「我的版本」左下角「启动器设置」与「管理 ▾」**:设置/实例详情已改为顶部标签页,这两入口冗余,已移除(保留「一键配置 ▾」)。
- **菜单栏精简 + 联机改标签卡(卡片形式)**:移除与「文件」同级的「设置」和「联机」菜单——设置已在顶部标签卡(检查更新移入「帮助」菜单,镜像源在 设置→界面);「联机方案中心」改为**「下载新资源」右侧的「联机」标签卡**,内部方案改**卡片形式**(名称+描述+打开官网,圆角卡片)。`OnlineCenterDialog` 改为可嵌入的 `OnlineCenter(QWidget)`。
- **联机主页化(参考下载新资源)**:联机标签卡改为「左侧菜单 + 右面板」——不同方案分类(帮我推荐/虚拟局域网/内网穿透/联机 Mod/官方方案/教程与资料)按左侧菜单排一列,复用 `CenterShell`。
- **AI 助手/游戏日志改为右侧标签页(可拖出子窗口)**:修复 AI 窗口"放不回去"——`ai_dock` 设 `AllDockWidgetAreas` + 可移动/可浮动/可关闭特征;把「游戏日志」从底部折叠面板改为**标签页**,与 AI 助手 **tab 并列**(点 AI/日志标签切换显示);两者都能**拖出主窗口变子窗口,拖回边缘贴回**。顶部「AI」菜单、「查看」菜单(实例大图标)已移除,「实例大图标」进入"已临时弃用/废案功能"登记;新手教程内容标注"AI 助手可拖出成子窗口"。
- **AI 面板收起→右边缘小条(小巧思)**:AI 助手下被 **× 掉/隐藏**时,不再完全消失,而是**收窄成贴在主窗口右侧边缘的一条**(竖排「AI ▶ 展开」),点「展开」立即恢复旁边栏;显示 AI 时自动收起小条。`setDockOptions`(AllowNestedDocks|AllowTabbedDocks|AnimatedDocks)修复了 dock 拖出后放不回。
- **菜单栏取消 + 入口收进标签页/设置**:移除「文件」「帮助」菜单——导入整合包走「下载新资源→实例→导入整合包」;「检查更新…」「重播引导教程」放进「设置→界面」;「刷新版本列表/清空所有实例/打开游戏目录」不再放外层入口(函数保留可调用)。
- **我的版本 → 我的实例(表达更精确)**:主标签改名;该标签下右列「版本」改为「实例(共x个)」(标签文本动态显示数量),删 "我的实例" 标题与「刷新」按钮——**切回该标签页自动刷新**;「一键配置」移到「启动游戏」上方,启动按钮下方不再显示"选中实例"小字(左侧「当前选择」卡片已展示);卡片标题「实例设置」→「当前选择」。
- **游戏日志挪进实例详情**:游戏日志从右侧 dock 移入「实例详情」左菜单的「游戏日志」项(常驻 log_view,实时流持续追加);删除独立日志 dock,右区只留 AI 助手。
- **我的实例首页**:「导入整合包」与「一键配置」**并排放在「启动游戏」上方**(导入在左);外层标签页字体调大(14px,用 tab_style);设置→界面 新增**🎨 配色(自定义主题)**:强调色/文字色/背景色可选择,改完保存持久化到 `ui_custom_colors`(整启动器下次重建生效,设置页立即预览)。**换掉 emoji 改用图标**已列入规划(灵感 #17,提上日程)。
- **无边框自定义标题栏(跨平台)**:窗口去掉系统边框,自绘标题栏(`frameless_titlebar.py`)——可拖动移动、双击最大化、最小化/最大化/关闭按钮;**按平台排布**:macOS = 左上角三个红黄绿灯点(保留 Mac 样式),启动器名称放右上角;Windows/Linux = 名称放左上角、最小化/最大化/关闭放右上角。"已有 x 个运行中的实例"指示放进标题栏;状态栏右下角尺寸拖拽手柄用于缩放。
- **标题栏改为全宽顶部条 + 去掉最大化按钮**:标题栏做成**顶部 dock(全宽)**,让右侧 AI dock 从标题栏**下方**开始(不再顶住上边缘),右上角留给**最小化**;**移除最大化按钮**(双击标题栏仍可最大化/还原)。
- **无边框/标题栏细化**:窗口标题与标题栏文字改为「**AMCL**」;AI 助手「展开」恢复为**停靠(不浮成子窗口)**,想要独立窗口直接拖 AI 标题栏拖出;「当前选择」卡片去掉下方小字;「启动器日志」改为「我的实例 → 启动器日志」与「MC 动态」同级的子标签页(游戏日志移出实例详情);下载球(进度指示)移到状态栏最右(窗口右下角);窗口补齐 `Qt.Window` 标志让任务栏点击最小化。
- **下载球 → 悬浮球**:下载指示器改为**可拖动的悬浮球**(无边框、置顶、半透明圆球),不再占状态栏底部;默认位置 = **内容区右下角**(AI 停靠时在 AI dock 左侧、主窗口侧外部,不占底部留白);随窗口缩放 / AI 显示/收起自动重摆。下载箭头改传统「下箭头」(同 AI 发送↑反向)。
- **无边框窗口的 Windows 补齐(任务栏最小化 + 四边/四角拉伸)**:新增 `win_frameless.py`——① 给窗口补 `WS_MINIMIZEBOX` + `WS_EX_APPWINDOW`(任务栏点击可最小化,保留左下角状态栏消息给用户确定感);② 覆盖 `nativeEvent` 处理 `WM_NCHITTEST`,让**四边 + 四角都能拉拽缩放**(返回 HTLEFT/RIGHT/TOP/BOTTOM/TOPLEFT/…)。该补丁仅 win32 生效(已在 Windows 上确认逻辑,需真机验证交互)。
- **启动器反馈全部进日志(方便 AI 定位)**:状态栏 `showMessage` 的消息 + **未捕获异常(traceback)** 都记进「启动器日志」,并**写文件 `.minecraft/logs/launcher.log`**(供 AI/排查读取);日志上限 2 万行。以后任何反馈都走进日志。
- **引导式新手教程(正式步骤)**:用 `guide_overlay` + `ui_route` 做了 6 步正式教学(启动游戏 / 导入整合包 / 一键配置 / 下载新资源 / 设置-界面 / 联机首页),入口「设置 → 界面 → 重播引导教程」,替换掉原来的演示步骤。
- **拖放安装(整合包)+ 拖入文件提示**:把文件**拖进主窗口** → 整窗发白覆盖层提示「**松手 → 尝试作为整合包安装**」→ 松手自动识别并导入成新实例(扁平包会先问游戏版本/加载器);格式不对给明确提示。**实例详情**:拖文件到 **Mod 列表区域 → 拷进该实例 mods 目录** 并刷新(新增 `DropListWidget`,同款可扩展到数据包/光影等列表)。
- **拖放按页面分流**:**只有「我的实例」页**拖入文件才是「整合包安装」;其它页面(设置/联机/下载新资源/实例详情)拖放交给各自控件——实例详情的 **Mod / 数据包 / 光影包** 列表拖入文件即**拷进对应目录**(mods/datapacks/shaderpacks)。
- **MCP server(stdio + HTTP 两种传输)**:`mcp_server.py` 手写 JSON-RPC 2.0,把启动器工具(agent_tools)暴露成 MCP 工具。`python main.py --mcp` = stdio;`python main.py --mcp-http [port]` = **Streamable-HTTP**,端点 `POST /mcp`,客户端可用「http」选项连 `http://127.0.0.1:8766/mcp`。支持 `initialize/tools·list(20)/tools·call/ping`。
- **设置→界面 新增「MCP 集成」**:一键**复制 HTTP 链接**、**生成客户端配置文件**(`AMCL/mcp_config.json` + `AMCL/mcp_http.cmd`,写到启动器创建的 AMCL 文件夹,含 http_url + stdio command/args)。
- **启动器 AI 作 MCP 客户端**:`mcp_client.py`(HTTP JSON-RPC 客户端,与 mcp_server 对称)。AI 可调用**外部 MCP 服务器**的工具——`assistant.available_tools(settings)` = 内置 TOOLS + 配置的 MCP 工具(`mcp__服务器__工具`),`build_executor` 路由 `mcp__` 调用到对应服务器。设置→界面「**MCP 客户端**」填入外部服务器 url(逗号分隔)即启用。**自环测试通过**:AI 客户端 → 启动器自己的 `--mcp-http` 服务器 → `list_instances`/`get_settings` 均返回。
- **崩溃诊断 · 修改意见清单(进阶①)**:新增技能「崩溃诊断·修改意见清单」——AI 诊断崩溃/异常时,先读日志(`read_instance_log`)与崩溃报告(`read_crash_report`),然后输出**结构化【修改意见清单】**(每条 = 改什么 + 为什么/怎么做,按严重度排序 + 1~2 条「先试」兜底 + 保留类名/Mod 名/路径),不再只给一段话。
- **MCP 客户端·模型侧接线(补全闭环)**:之前 `available_tools(settings)` 已实现但**没接进请求的 `body["tools"]`**,导致模型"看不见"外部 MCP 工具、选不到。现在 `mount_tools_for(text, settings)` 在截断之后**追加**配置的 MCP 工具 schema(不超限也不砍掉),云端请求即带上 `mcp__服务器__工具`。自环实测:AI→启动器 `--mcp-http`→`mcp__amcl__list_instances` 返回真实实例列表;`available_tools` 由 20 → 39(含 19 个 MCP 工具)。
- **MCP 客户端支持 stdio 传输(接 MC 资料库 MCP)**:调研发现**几乎没有公网托管的 HTTP MC 资料库 MCP**(唯一托管实例 `minecraft-wiki-mcp.goett.top/mcp` 实测间歇 403、限流不可靠),可靠的是**本地 stdio**。于是给 `mcp_client.py` 加 `MCPStdioClient`(一行一个 JSON-RPC 消息,逐行读写子进程 stdin/stdout),`connect_mcp_clients` 支持 `{transport:'stdio', command:...}`(命令字符串用 shlex 拆,支持带空格的路径/quoted)。HTTP 客户端补上 Streamable-HTTP 必需的 `Accept: application/json, text/event-stream` 头 + `Mcp-Session-Id` 会话透传。**设置→界面 MCP 客户端**框改为用 `;` 分隔(兼容旧逗号),每条两种写法:`http://…/mcp` 或 `名字>=本地命令`(如 `mcwiki>=uvx mc-wiki-fetch-mcp`)。自环实测:stdio 客户端→启动器 `--mcp` 服务器→19 个工具、`list_instances` 调用成功。
- **本地名称归一化(查 wiki/资料库更准)**:新增 `mc_names.py` + 工具 `resolve_mc_name`——把中文/口语/英文叫法解析成**规范 MC 英文名 + id**(如 苦力怕 → `Creeper`/`minecraft:creeper`、锋利 → `Sharpness`)。读实例 mods jar + 版本 jar 的 `zh_cn.json`/`en_us.json`(含**物品/方块/生物/效果/附魔**,此前 `recipe_graph` 只读物品/方块)+ 内置原版常见词表(离线兜底)。查不到则明确说"本地没查到",不硬造 id。已接 `TOOL_FUNCS`/`TOOLS`(21 个)并挂到云端 log 组(命中 崩溃/wifi/名称/百科 关键词);新增技能「本地名称归一化」(ai_hint 指引 AI:查 wiki 前先用 `resolve_mc_name` 归一化)。
- **自定义配色「实时整应用上色」**:之前改主题色要**下次重启/重建才生效**(各页面在构造时把 `current_color()` 值固化进 setStyleSheet 字符串)。现在 `ui_style` 新增**登记式刷新**:`set_style(widget, style_fn)` 代替 `widget.setStyleSheet(style_fn())`(同时登记该控件),换色后 `refresh_theme()` 用最新配色重刷所有登记控件。已把 119 个控件(左菜单/主标签页/启动按钮/卡片/列表/面板/设置按钮等)改用 `set_style` 登记;设置→界面 改色/重置后立即调用 `refresh_theme()`,整应用实时变色。`refresh_theme()` 还会重刷全局调色板(暗色下默认控件/对话框/菜单/下拉的强调色联动);新增 `accent_border_style`(右侧 AI 条展开按钮,悬停强调色)。
- **配色可读性检查 + 色盲/色弱模板**:`ui_style` 加 **WCAG 对比度/明暗/色差检查** `check_readability()`——文字 vs 背景对比度 <4.5 提示"可能看不清",强调色与背景过近、明暗接近(色弱难分辨)也提醒。自定义改色后自动在设置页显示✅/⚠️提示(半透明背景按当前深浅色叠到窗口色判读)。新增 **4 个无障碍配色模板**(只覆盖强调色一族,文字/背景随深浅色自动走,两种模式都可读):高对比、红绿色盲(蓝/黄)、蓝黄色盲(红/绿)、灰度友好。设置→界面 加「配色模板」下拉 + 应用按钮,一键套用。
- **资源中心图片显示优化 + Mod 图片/描述缓存**:新增 `image_cache.py`——Mod **图标**与**描述翻译**按 **slug(项目名)缓存**(内存+磁盘在 `AMCL/cache/{icons,desc}`),**不同版本/加载器同一 Mod 复用**(换版本不重复下载),跨线程/并发"重复注册"用线程锁+原子写去重,安全。缓存 TTL 30 天。**图片不显示修复**:① 搜索结果条目 & 详情面板图标改用缓存拉取(命中即秒回,不每次都 `requests.get` 失败白屏);② 失败/无图用灰色圆角方块+项目首字**占位**,不再空白;③ 描述翻译命中缓存直接显示(标"⚡已缓存翻译"),不再每次推理。设置→界面 加「清除图片缓存 / 清除描述翻译缓存」按钮。
- **图标按需懒加载(降低缓存开销)**:之前一进搜索页就**并发拉满 30 条的图**,即使大多数条目用户没滚到/没点开,开销大。改成**可见性驱动 + 串行**:只给**当前视口内可见**的行按顺序(从上到下)拉图并缓存,用户还没看到的**先不拉不存**;滚动/改变大小/列表变化时重新计算可见行,增量入队。实测 30 条结果初始只加载约 6~11 条(可见的),滚到底后增至 17~21 条——不再一进场就 30 个并发请求。
- **Mod 图标改到资源卡片左侧**:之前图标显示在**详情面板顶部**(56×56)。现在 Mod 图标放在**搜索结果卡片(列表项)左侧**(`setIconSize 44×44`),列表里一眼能看到;详情面板不再放大图(去掉 `icon_label`)。修复"图片不显示":跨线程结果改用与网络请求同一条 `_async_q` 通道回主线程,避免 worker 线程 `QTimer.singleShot` 丢回调(之前图标加载了却永不 set 到 item 上)。
- **图标占位框(文本不再重排)**:每个列表项在 `_fill_results` 时**预置一个固定 44×44 的占位 QIcon**(淡灰圆角方块),QListWidget 自动给带图标的项在左侧留图标位 → **文本始终从固定 x 开始**;懒加载到的真图标**只替换占位**,文本位置不变(加载前后不重排、不跳动)。真图标加载失败/无图时占位框保留,不留空白。
- **一切皆插件(骨架)**:新增 `plugin_manager.py` —— 插件 = `plugins/*.py`,提供 `register(api)`,`register` 支持 **4 类注册点**:AI 工具 / GUI 页面(章节)/ 设置项 / 技能(Skill)。**启动时静态装载**,启禁存 `settings["plugins_disabled"]`(设置→插件 勾选,下次启动生效);核心组件(启动/实例/下载/设置/AI)不插件化保持稳定。已把插件工具并入 `assistant`(available_tools/mount_tools_for/executor 都能看到并调用),插件技能并入 `skill_manager`(被 ai_hints 注入 AI 提示)。设置→插件 新增管理页(列插件+启禁开关+注册内容+插件页面预览)。附带 `plugins/hello.py`(演示 5 类),模板文档 `plugins_templates/插件模板.md`(给用户的 AI 生成新模块用)+ `plugins_templates/模块分析.md`(核心 vs 可选模块划分)。
- **插件:默认关闭 + 独立设置行**:① 插件可设 `PLUGIN_DEFAULT_ENABLED=False`(**默认关闭**)——设置→插件 里勾选启用才生效(适合 MCP 服务器等按需功能);默认关的插件在 设置→插件 标"🔒 默认关闭"提醒。② 插件可用 `api.register_settings_page(build_fn)` 注册**独立设置页**,设置→左菜单**为该插件单独开一行**(名为 `插件:<插件名>`)。`plugin_manager.load_all(settings)` 支持 默认关+显式启用(plugins_enabled)逻辑;MCP 服务器 计入"可默认关闭的插件"候选。
- **下载新资源 · 启动器插件占位**:「下载新资源」左侧菜单 + 首页卡片新增「🧩 启动器插件」(第 8 项)。点击进入**占位页**——说明插件生态建设中、列已装载插件(如 示例插件)、带「打开插件管理(设置→插件)」按钮一键跳转。插件浏览/一键安装留待生态成型。
- **联机 CLI 桥接插件(示例)**:新增 `plugins/lan_bridge.py`——把联机方案中心从"只会跳官网"升级成**实际可调的命令行桥接**:检测(EasyTier/ZeroTier 是否已装,`shutil.which`+常见路径)、一键组网(生成房间名+密钥)、拿虚拟 IP 分享给朋友(`--no-tun` 免管理员)。注册 **2 个 AI 工具**(`lan_bridge__lan_status`/`lan_bridge__lan_setup`)+ 独立设置页(设置→左菜单单开「插件:联机 CLI 桥接」,含检测状态/生成房间)。`online_center._lan_tools()` 优先路由到该插件工具(旧 `lan_tools` 约定降级兜底),让联机中心的「一键生成房间」真正可调。**不内置二进制**(EasyTier 等由用户官网下载);未装则优雅提示。
- **语言管理 + 语言包插件**:`i18n` 加**语言包覆盖层**——`t(zh, en)` 不改任何调用点,先查当前生效语言包(用**中文/英文原文作 key**,语言包 = `{"原文": "替换文本"}`),命中用语言包文本,未命中回退内置 zh/en;支持 `set_language(pack_id)` 激活整包换肤。**语言做成可选插件**:插件用 `api.register_language_pack(id, name, pack, lang)` 注册语言包(新增 `plugin_manager.LANGUAGE_PACKS`);也支持第三方直接丢 `.json` 到 `AMCL/languages/`(`load_packs_from_dir`)。设置→界面 语言下拉自动列可用语言包(选中即整包替换)。附带 `plugins/meme_lang.py`(玩梗语言包,`PLUGIN_DEFAULT_ENABLED=False` 默认关)。修复 `discover_plugins_meta` 侧效应泄漏(探测时隔离 i18n 包注册表)。
- **MCP 服务器模块化成"默认关闭插件"**:`mcp_server.py` 加可启停的 `MCPHttpServer`(后台线程,不阻塞 GUI);新增 `plugins/mcp_server.py`——**默认关闭**(`PLUGIN_DEFAULT_ENABLED=False`,按需启动,不占端口),注册 **AI 工具 `MCP服务器__mcp_status`**(查服务是否运行)+ **独立设置页**(设置→左菜单单开一行:配置端口/启动/停止/显示连接 URL)。CLI 旧方式(`python main.py --mcp` stdio / `--mcp-http [port]` HTTP)保留、与插件互不影响。设置→界面 语言下拉已列内置+用户语言包。
- **设置→插件 管理页 UI 优化**:① 整页放进**滚动区**(垂直拥挤可滚);② 启用/禁用改用**开关样式**(iOS 风格 `ToggleSwitch`),默认关闭的插件**不再写"默认关闭"文字**(开关是关即说明);③ 插件**标题调大**(15px)、描述不变;④ **注册内容移到 tooltip**(悬停才显示),不再常驻占行;⑤ 有**独立设置页**的插件在开关旁加**⚙ 齿轮按钮**,点击跳转到该插件设置页(未启用则提示先开开关)。
- **设置「界面」「AI 助手」页加滚动区 + 语言包合并**:`_build_ui`/`_build_ai` 包进 `QScrollArea`(纵向不拥挤);MCP 集成已成独立「MCP」章节。「玩梗语言包」从独立插件改为**内置语言包**(`languages/meme.json`)——语言包统一为"可加载文本包"(插件可 `register_language_pack` 贡献 + 第三方丢 `AMCL/languages/*.json`),不必单独成插件;所有语言包(含机翻生成的 en/fr/es…)统一出现在 设置→界面→语言 下拉。
- **MCP 全靠插件,不再留独立「MCP」菜单章节**:删掉设置左菜单的独立「MCP」章节,MCP Server 链接/生成配置 + MCP 客户端(外部服务器)全部并入 **mcp_server 插件的设置页**。这样 **mcp_server 默认关闭时左菜单无任何 MCP 相关项**(符合"关闭的插件不显示菜单");启用插件后才出现「插件:MCP Server」设置页,内含 server 启停 + 客户端配置。`apply()` 改为从插件设置页读取 MCP 客户端配置(找不到时保留原值)。
- **能用 AI 生成插件**:① `plugin_manager` 加 `save_plugin`/`validate_plugin_code`(语法+ASt 校验 register 存在 → 落盘 `plugins/<name>.py`);② AI 新增工具 **`create_plugin(name, code)`**——当用户需求超出现成工具/页面能力时,AI 生成一段符合插件模板的源码并落盘;③ 新增技能 **「插件生成指南」**(ai_hint 引导 AI:先判现有工具能否覆盖→不能才生成插件→create_plugin 落盘→提示重启生效→安全提醒);④ 设置→插件页右上角加 **「重启启动器生效」** 按钮(插件启停/新增后手动重启)。插件是**静态加载**,生成后需【重启启动器】才生效(热加载留作后续)。
- **插件可注册主标签页**:插件协议新增 `api.register_main_tab(label, build_fn)`——插件能注册一个**与「下载新资源/联机/设置」平级的全新主标签页**(不只是挂某页里的章节)。`MainWindow` 构建时把启用的插件标签页 `addTab` 进主标签栏。示例插件加「示例标签」演示。修复 `discover_plugins_meta` 探测时向 `MAIN_TABS` 泄漏(导致重复 tab)。插件模板补 `register_main_tab` 示例。
- **启动器插件商店(两步走)**:① `plugin_manager` 加**仓库能力**(`load_registry`/`list_remote_plugins`/`install_remote_plugin`)——从仓库源(plugins.json 清单)拉插件列表,下载单文件 `.py` 落盘(复用 `save_plugin` 校验+写盘;支持 http(s)/file)。② 「下载新资源」插件页升级成**商店**:手动**添加/删除仓库源**(存 `settings["plugin_registries"]`,你的官方仓库 URL 可作默认),列出仓库里的插件(名/版本/描述/来源),**一键安装**单文件 + 提示重启生效。参考 DSH「仓库即商店」:你的官方插件放你项目仓库,别人加你仓库 URL 就能装。
- **「我的实例」页 · MC 存储路径下拉 + AI 权限默认只读**:①「我的实例」页加「存储路径」下拉——列出当前游戏目录 + 历史路径 + 「＋ 添加新路径…」(弹目录选择),选任一即 `set_game_dir` + 存设置 + 记录历史(`game_dirs_history`)+ 刷新实例列表。② **AI 文件权限默认只读**(settings 默认 `readonly`,重置 config);在 AI 面板把权限从「只读」切到「**工作区可写**」时,弹出**二级确认 + 免责声明**(说明 AI 将能改 工作区/AMCL/游戏目录 内文件、写操作前备份、可随时切回只读),点「否」保持只读。
- **全局键盘导航框架(遥控器式)**:新增 `keyboard_nav.py`——顶部**分类标签 ←/→ 切换**、页内**左菜单 ↑/↓ 切换**、**Enter 进入当前菜单分项**。**防抢键**:焦点在实例列表/按钮/输入框等「自己会消费按键的控件」上时不导航(不干扰 列表上下选+回车启动、输入框打字);焦点在空白背景时才导航。`MainWindow` 装 `install_global_nav`(带 page_menu_fn 取当前页左菜单)。
- **存储路径下拉移到「实例(共x个)」标签页内**:把「我的实例」页的「存储路径」下拉从左侧登录区移到右侧「实例」标签页(实例列表上方),切换游戏目录后实例列表就近可见。逻辑不变(当前/历史/添加新路径,选后 set_game_dir+记录历史+刷新实例)。
- **AI 面板 · 聊天记录·归档标签页**:AI Dock 改为**双标签**(💬 聊天 + 🗂 记录/归档)。新增 `chat_archive.py`:把当前对话存成会话(`AMCL/chat_archive/`,含 `chat_messages` 喂给 LLM 的历史 + `entries` 展示流,工具条目可序列化/恢复);归档 tab 支持 **💾 存档当前**、**↩ 恢复选中**(替换历史可继续提问、含工具过程)、**删除**、切到归档自动刷新列表(标题/时间/条数)。从已归档可快速恢复。
- **语音输入方法骨架(微信式 Ctrl+Win 接管光标)**:新增 `voice_input.py`——`GLOBAL_HOTKEY="ctrl+win"` + `hold_to_talk_hotkey()`(供以后插件注册全局热键)、`insert_at_cursor(widget, text)`(**文字插到当前光标处**,实测光标位置 1 插入→`aXXbc`)、`record_and_transcribe`/`record_from_mic`(ASR 占位)。AI 面板输入框加 🎤 占位按钮。**真实语音识别留作以后插件落地,现阶段只写方法**。
- **设置→AI 权限下拉也加升权限确认**:权限下拉从「只读」切到「工作区可写」时,同样弹**二级确认+免责声明**(取消则回只读),与 AI 面板的「切换」按钮一致。
- **修复插件启禁未真正生效(示例标签不随关闭隐藏)**:`load_all(settings)` 原本**没读 `settings["plugins_disabled"]`**,传 settings 时禁用集为空,导致禁用插件仍被加载(其注册的内容/标签都在)。改为禁用集 = 显式传入 disabled 并上 `settings["plugins_disabled"]`;禁用 Hello → `MAIN_TABS` 空(示例标签隐藏),启用 → 出现。


- **名称解析·深挖(口语/别名/模糊 + 接进配方)**:`mc_names.py` 加 **440 条口语/别名/近义表**(如 会爆炸的怪/爆爆怪/绿皮怪→creeper、小黑→enderman、时运→Fortune)+(拼音/前缀/中文子串)**模糊匹配**(`cree`→creeper、`苦力`→苦力怕);新增 `resolve_for_wiki(query, wiki_lang)`——按目标 wiki 语言返回该用的检索名(英文 wiki 用 `Creeper`、中文 wiki 用 `苦力怕`)。并把别名表**并进 `recipe_graph.build_zh_index`**,让 `get_recipe_path`/`compare_items`/`resolve_item` 也吃口语叫法(`会爆炸的怪`→`minecraft:creeper`);`resolve_item` 复用下划线 compact 兜底。

### 🧩 Mod 依赖网络(灵感 #5,简单版)
- 实例管理 → Mod 页新增「**Mod 依赖网络**」:离线解析该实例各 mod jar 的依赖/冲突,画成一张"谁依赖谁"的网
- 解析:`mod_deps.py` 读 `fabric.mod.json` / `mods.toml`(required/optional/incompatible),标出缺失依赖(装了 A 缺 B)
- 渲染:`mod_graph.py`(QGraphicsView 力导向布局 + 拖拽平移 + 滚轮缩放;蓝=已装 / 灰=已禁用 / 红=缺失;
  实线=必须依赖 / 虚线=可选 / 红虚线=不兼容),带图例+概览
- **大型整合包不再挤**(2026-08-24):画布按节点数自动放大 → 打开时整体 fit 到一屏(缩得更小、看全貌);节点宽度收紧(最长 110),长名看 tooltip;新增**搜索定位**(输入 mod 名/id 回车跳到它)、**缩放控制**(⌖适应/+/-)、**点节点高亮**(它 + 直接依赖/被依赖的节点全亮,其余变淡,再看"哪里在调")、取消高亮
- 入口点击先出"正在分析依赖关系…"进度条(后台解析,不卡界面)
- **下载 Mod 时正向依赖提示(灵感 #4 剩余)**:资源中心下载 Mod 时,按 Modrinth 版本 `dependencies` 提示
  "需要(必装)/可选/冲突",可一键一并安装缺少的必需依赖(`modrinth.resolve_dependencies`)

### 📦 整合包导入(多格式,自动识别)
- 导入整合包不再只认 Modrinth `.mrpack`:**自动识别** `.zip` 内部是哪种整合包
- 支持:① **Modrinth .mrpack**(清单式,下载清单文件+解压 overrides)② **CurseForge .zip**(读 manifest 拿 MC 版本+加载器,
  自动装基础+加载器+解压 overrides;清单列的文件需 CurseForge API,已明确提示跳过)
  ③ **扁平 .zip**(无清单的实例文件夹:含 mods/config/shaderpacks/saves 等,如 FTB/手工包——导入时填 MC 版本可选项加载器,
  自动解压成新实例;单一顶层包装文件夹会自动剥离)
- 入口:文件菜单「导入整合包(.mrpack / .zip)…」;识别为扁平且缺版本时,会先询问游戏版本/加载器
- **本次强化(2026-08-24)**:
  - **并行下载**:整合包里的 mod 文件(如 258 个)改为 6 线程并行下载,逐文件报进度+文件名,单文件失败跳过不中断
  - **加载器支持补齐**:`_install_loader_from_deps` 之前只认 fabric-loader/forge,现支持 **neoforge**(quilt-loader 视为 fabric)
  - **一开始就建实例目录**(不再等基础版+加载器都下完);导入失败自动**回滚删除**实例目录,不留半成品
  - Forge/NeoForge 的 **forge 版本号要拼 MC 前缀**(如 `1.20.1-47.4.0`,`47.4.0` 会 404)——CurseForge/Modrinth 常给裸版本,已归一化
  - Forge/NeoForge 安装的全链路进度接入:base jar / 资源索引 / installer / Java 17 / 补丁步骤 / 解压 overrides 都会动进度条
  - 入口改为「导入整合包(.mrpack / .zip)…」,同名实例会让用户自定义命名(不再直接报错)
  - **「打小抄」改名为「实例记录」**,`versions/实例记录.json`(结构化,保留用户备注,自动清理旧 txt)
  - **AI 直接下载整合包(工具):** AI 助手新增 `search_modpacks`(搜 Modrinth 整合包)+ `install_modpack`(下载 `.mrpack` 并导入成新实例,自动装基础+加载器+mod)。
    若整合包**不在 Modrinth 上**,返回友好提示并引导用户用网盘/官方链接下载(由云端 AI 产出下载方案);传错成"单个 Mod"也会明确纠正。

### ⚡ 性能策略(AI 规划 §5,LLM 运行时的游戏影响)
- **量化提示**:本地推理时后台每秒采样 llama-server CPU 占用,状态栏显示「推理中… CPU≈X%」,给用户判断依据
- **主动避让**:检测到游戏进程启动 → 本地推理降到游戏优先级之下;游戏运行中且「游戏内 AI」非本地时暂停本地推理
  (提示,不再抢资源);游戏退出后恢复并自动预热
- **用完即卸**:本地推理结束后闲置 60s 自动卸载模型回到空闲态(`ai_in_game=local` 时保持常驻,供游戏内用)
- **温控意识**:推理前探测 CPU 温度,≥85℃ 时劝退重任务/建议上云端(每 5 分钟最多提醒一次)
- **冷启动预加载**:保留 §8.2 预热;游戏运行且非本地通道时不再预热(不与卸载打架),游戏退出后再预热

### 🐛 修复
- **整合包导入 worker `UnboundLocalError`(选完文件没反应的真凶)**:`import_modpack` 的 worker 里返回值变量与闭包
  `instance_id` 同名,Python 视其为局部变量、读未赋值 → worker 秒崩 → 界面"选完整合包没反应"、`.minecraft` 零写入。
  已把返回变量改名为 `done_id` 隔离。
- **下载进度条常驻 + 下载详情非模态**:下载完成不再自动收起环形指示器(常驻,点击看详情);详情窗改 `show()` 非模态
  (不强制置顶/不阻塞,可边看进度边操作,实时刷新)。
- **本地模型选择后仍走云端 401**(t14):选「内置本地模型」却请求云端、报"API Key 无效或未配置"。
  根因:本地路由只看 `ai_provider`,旧/默认配置下 `ai_provider` 仍是云端 provider(如 `deepseek`),
  于是按云端发请求撞 401。修复:① 本地路由改按 AI 策略(local_first/hybrid)判定,不再依赖可能
  过期的 `ai_provider`;② 云端通道校验按「公网地址 + 密钥」(本地地址如 localhost 免密钥),没配密钥
  视为云端不可用并给友好提示,而不是撞 401;③ 本地策略下落到云端时统一取 `ai_cloud_*` 那组配置,
  避免内置模型空 base_url 拼出无效 URL。
- **旧配置自动迁移**(t14):`load_settings()` 读旧版 config 时自动把「单一 ai_provider」拆成云端/本地
  两组,并按 provider 推导连贯的 `ai_strategy`(本地→local_first / 云端→cloud_first),升级后写回磁盘一次;
  未配过 AI 的新/旧配置保持产品默认 `local_first`,不误改。旧用户用新版本不再出现"策略显示本地、实际走云端 401"。
- AI 对话 worker 线程跨线程操作 Qt 部件 → 原生崩溃(0xC0000005/0x8):改信号队列 + 销毁竞态防御
- 云端请求配置错误时干等 3 分钟:超时拆分 + 友好错误,15 秒内明确提示
- llama.cpp 启动弹命令提示符(加 CREATE_NO_WINDOW);更新日志 GitHub 拉取失败态
- **整合包实例启动"白板"(mod 全不加载)+ 多出一个空白实例(2026-08-24)**:导入整合包时,
  版本 json 是从加载器版本复制来的,其 `id` 仍是加载器名(如 `neoforge-21.1.233`),没改写成包名。
  启动时 `game_dir_for(d["id"])` 于是解析到**加载器的空白目录**(没 mod),游戏跑到那里启动 → 白板;
  而整合包自己的 260 个 mod 装在 `versions/<包名>/mods` 里却没加载。修复:
  ① 导入时把复制来的 json `id` 改写成整合包实例 id;② 启动时游戏目录改用**所选实例 id**(`v["id"]`),
  不再依赖 json 内部 id(json 可能来自旧版/被复制);③ 加载器框架版本(纯空白、无人引用)导入后自动
  收进 `versions/_versions/` 仓库,不再残留成"多出来的空白实例";④ 启动前自动自愈旧版导入的包
  (发现 json `id` 与目录名不一致就改写,无需重新导入)。
- **Modrinth Mod 下载补 sha1 校验**(网络差损坏 jar 会被检出重下)

---

## [v0.2.1] - 2026-08-23

### 🧠 AI 助手
- **真正的多轮记忆**:历史消息(含工具调用过程)全部传给模型,前文不再丢失
- 图片输入:📷 选图 / Ctrl+V 粘贴 / 🖼 最近截图(.minecraft 里自动找 F2 截图)
- 上下文占用环环绕发送按钮(绿→黄→红,悬停看具体 tokens),超限自动裁剪历史
- 新增 `install_instance` 工具:AI 一句话就能下载/创建实例(原版/加载器/Mod)
- 配方树 EMI 化:一个物品列出全部合成方式 + recipe_index 切换展开 + 常用物品中文名

### ⚡ 性能
- 加载器选择异步化:点卡片 0.003s 响应(原 1-3s 卡顿),版本/Mod 列表后台加载+缓存
- 下载并行化:依赖库/资源/Mod 同时下(3-5×提速)

### 🔄 自动更新
- 帮助 → 检查更新:从 GitHub Releases 拉新版一键替换重启;同时检查 bridge-mod

### 📦 便携与目录
- 数据存 exe 旁边(PCL 风格),配置收进 AMCL/ 防误删
- 版本仓库:加载器带出的基础原版收进 versions/_versions/,versions 只留真实例

### 🐛 修复
- 启动 Java 下载报 progress_bar 不存在;QPen(cap=) PySide6 崩溃
- 整合包加载器识别(D 盘 ATM10→NeoForge);Java 压缩包损坏自动重下
- 下载/启动弹 Java 黑框 → javaw + CREATE_NO_WINDOW;运行实例指示(状态栏)

---

## [v0.2.0] - 2026-08-22

首个公开版本。AI 助手型启动器,面向社区/朋友尝鲜。

### 📦 自动更新
- 帮助 → 检查更新:对比 GitHub Releases,发现新版本可一键下载并自动替换重启
- 同时检查 bridge-mod 的发布情况
- **发版规范**:AMCL 每次发版打 `vX.Y.Z` tag + Release(附 `AgentMinecraftLauncher.exe`);
  bridge-mod 单独 tag(如 `v0.1.0`),附 `agentmc-bridge-fabric/neoforge-*.jar` 资产
  —— 启动器的"检查更新"靠这个规范工作

### 🚀 新增(AI 助手)
- AI 停靠面板:与 DeepSeek / Ollama / LM Studio 对话,工具调用驱动操作
- **工具调用**:列出/搜索实例与 Mod、读日志与崩溃报告、装 Mod、建实例、备份、改设置、
  发游戏指令、查配方、查按键绑定、查指令指南
- 权限控制:只读 / 工作区可写两档,写操作需授权
- 技能系统:崩溃看门狗、自动重启、备份提醒、指令指南(版本感知 NBT 写法)

### 🚀 新增(实例与版本)
- PCL2 风格实例目录(`versions/<id>/`),共享 libraries/assets/runtime
- 版本树:大版本分组、愚人节版本分类、黄金版本 🏅 标记、发布年月列
- 创建实例:原版 / Fabric / Forge / NeoForge + Fabric API + 光影 + 优化 Mod
- 整合包导入、Mod 启停、运行配置、一键备份(GUI + AI 自动备份)

### 🚀 新增(Mod 与联机)
- Modrinth 中文搜索、推荐 Mod 列表、Mod 卡片二级菜单
- 联机方案中心、Lan Server Properties 自动配置、RCON 通道
- 指令中心:常用指令模板 + 每实例指令库

### 🚀 新增(bridge-mod)
- 自制 Mod(fabric / neoforge):本地 TCP 指令口(127.0.0.1:26100)+ 数据导出
- 一键配置:默认 bridge 方案(自动下载),RCON 为临时备用
- 配方 / 物品属性 / 按键绑定导出,供 AI 精确查询

### 🚀 新增(配方分析)
- 套娃合成展开:完整合成树 + 每步机器标注 + 材料总账(自动向上取整)
- **中文名索引**:从 mod jar 语言文件构建 中文/英文名 → 物品 id 映射,直接输中文可查
- 配方数据自动定位:自动探测所有实例,取最新导出的配方数据

### 🎨 界面与体验
- 深色模式、i18n(中文/英文自动跟随系统)
- 左下角环形下载指示器 + 下载详情对话框
- 命令行 CLI(`python cli.py ...`)

### 🐛 修复
- 原版(不选加载器)无法开始下载实例
- 加载器版本下拉挤在卡片内导致卡片拥挤(改为面板底部独立版本行)
- 配方数据已导出却查不到(工具未按实例定位数据)
- 套娃合成中"拆块配方"(1 矿块→9 材料)循环放大导致数量爆炸
- NeoForge 事件总线注册错误导致启动崩溃(移入 NeoForge.EVENT_BUS)
- bridge 指令口 IPv6 回环地址(::1)绑定失败(显式绑定 127.0.0.1)
- bridge-mod 分发 sha1 与线上 jar 不一致导致下载失败

### ⚠️ 已知限制
- 仅离线账号模式;正版登录计划 v1.0
- Forge(1.19 及以前)加载器晚点支持
- Mekanism 等 mod 的"冶金灌注/特殊工序"配方原料 bridge 未导出,
  配方树中标注"需游戏内确认"(规划直接读 mod jar 配方解决)
- 测试阶段,可能有 bug,欢迎反馈

---

## [未发布 / Unreleased]

> 📌 **许可**:项目许可改为 **GNU AGPL-3.0**(仓库根 [LICENSE](LICENSE)),采用 AGPL-3.0 开源许可。

### 📦 资源中心与更新(2026-08-24 迭代)
- **资源中心 Mod 列表打开即默认加载**:进入 Mod / 光影包 / 数据包 / 资源包页即展示热门列表,无需先点搜索
- **Mod 中文名对照表**:自建 Modrinth Top-100 清单,与现有对照表合并后共 **141 条**;搜索结果与详情标题优先显示中文名
- **Mod 详情「在 MC百科查看」链接**:详情面板新增入口,一键在浏览器打开该 Mod 的 MC百科(mcmod.cn)搜索页
- **自动更新修复**:重启不再报 PyInstaller 父进程校验失败;内置版本号升至 v0.3.0

### 🎨 界面与体验
- 「我的版本」首页仿 PCL2 重做:左 1/3 登录卡片(头像/昵称/登录方式 + 更改登录入口)与
  当前实例卡片、启动游戏大按钮、版本选择/版本设置按钮
- 右 2/3 改为标签页:版本选择 / **启动器更新日志**(解析 CHANGELOG.md)/ MC 社区动态(占位)
- 登录方式入口:目前仅离线(可改昵称),正版/外置登录为规划占位
- 设置入口收敛:启动游戏下方改为「启动器设置」+「管理 ▾」,后者整合实例管理/整体设置/版本选择
- 整体 UI 视觉打磨:主题自适应配色、圆角卡片、渐变启动按钮、列表圆角高亮
- 默认离线游戏名改为 Steve
- 「下载新资源」逻辑与界面重构:目标实例全局共享(各分类页一并生效)、
  搜索/项目详情/版本列表异步化(不再卡 UI)、详情面板版本/加载器下拉填活(真正驱动下载)、
  主题自适应视觉统一
- 「下载新资源」目标实例卡片改为可滚动区域:实例再多展开也不把筛选/搜索挤出界面
- 首页分类卡片改响应式流式布局:窄窗口自动换行,不再重叠
- AI 助手停靠栏:顶部新增当前模型 + 是否支持看图徽标;按所选模型是否多模态自动显隐
  📷/🖼 图片按钮(可判定的模型自动开/关,本地/自定义未知模型保留手动开关)
- AI 助手停靠栏视觉打磨(标题栏、模型徽标、历史区、权限/技能按钮统一圆角样式)
- **本地 AI 模型前端接入**:设置新增「内置本地模型」provider(local_builtin,无密钥,模型 qwen3.5-0.8b-xlam-q4km);
  首次用到且未下载时后台自动下载(镜像优先)+进度弹窗,期间转云端不报错;
  顶部徽标常驻显示本地模型状态(未下载/下载中/已就绪/推理中);
  多模态按 provider 自动预设(local_builtin→关 / openrouter→开,可覆盖);
  新增 `ai_in_game` 下拉(off/cloud/local),游戏启动时 off/cloud 卸载本地模型、local 保留;
  窗口关闭卸载本地模型,无残留 llama-server 进程;
  首次引导页新增「内置本地 AI 模型」提示;
  §8.2 冷启动预加载:选中内置本地模型且模型已下载时,开机空闲期后台预热 llama-server,
  首次本地提问不再等 server 冷启动(状态栏显示"预热中")
- AI 设置拆分:云端 / 本地两大块分开配置(顶部「当前使用」单选),各自保存自己的服务商/接口/密钥/模型
  (云端)与内置/Ollama/LM Studio/自动下载(本地),按来源推导生效的 ai_provider 等,后端零改动
- 移除死亡代码:旧「下载 Mod」页(tab_b)及其专属成员,AI 助手不依赖它

### 🧠 游戏内 AI 通道设计(§5.1,2026-08-23 决策)
- 新增设置项设计 `ai_in_game`(off/cloud/local),决定游戏启动时本地模型去留:
  off/cloud → 卸载(省内存给游戏);local → 常驻服务游戏内 AI(bridge-mod 未来入口,日程见 ROADMAP)
- 已写入 AI规划.md §5.1 + 任务书 W7,前端实现待多模态模型执行

### 🧠 聊天循环接入本地路由(W3,§1 落地)
- `assistant.py` AIChatDock 新增 `_local_enabled` / `_get_local_engine`(懒加载单例)/
  `_local_model_ready` / `_local_tool_call`(grammar 调用 + 复用 executor 执行)
- `send()` 的 worker 按 `task_router.route()` 分流:rule 直接答 / local 走本地(失败落云端 §1.4)/
  其余走云端 chat_with_tools(未动)
- 默认 provider=deepseek → 本地路径不启用,现有云端行为零影响
- 集成验证:rule/local/cloud/ask 全链路通过,本地真实执行 list_instances / set_setting 成功

### 🧠 任务路由与失败链路(规划 §1)
- 新增 `task_router.py`:难度判定(诊断/代码/规划=难,翻译/摘要/分类=易)+ FAQ 规则引擎 + 失败链路
- 优先级:工具动词→本地 / 纯问答→规则 / 困难→云端 / 歧义→ask / 未知→云端兜底
- `run_with_fallback`:本地 → 规则引擎 → 云端 → 诚实认输,每层失败自动落下一层(§1.4)
- 歧义请求(推荐/该装哪些/你决定)架构层强制 ask_user:直接构造问题+候选选项,不依赖小模型自觉
- schema 单一来源:`local_ai` 从 `assistant.TOOLS` 自动生成 GBNF —— 新增工具只改 assistant.py 一处

### 🧠 已知问题修复(§8.1 实测反馈)
- **ask_user 触发不灵** → 路由层架构级兜底(见上)
- **compare_items 英文参数** → 描述强化 + `recipe_graph.compare_items` 英文别名映射(damage/armor/toughness/speed,大小写/空格容错)
- **"启动实例"误解** → install_instance(创建)/launch_game(启动)描述区分,本地 TOOL_DESCRIPTIONS 与云端 TOOLS 同步
- 修复后 grammar 全量回归 78.5%(修复前 76.6%),无回归

### 🧠 AI 本地推理模块原型(规划 §7.1 / §8.2)
- 新增 `local_ai.py`:GrammarToolEngine —— 自动从工具 schema 生成 GBNF grammar,
  用自带 llama.cpp server(b10590)加载 xLAM Q4_K_M,输出结构 100% 合法 JSON
- **grammar 约束解码实测有效**:31 条测试集 ×3 次平均,参数准确率 79.0% vs 原生 tools 69.4%(+9.6%),
  验证"结构上必对"——required 字段强制必填
- 踩坑记录已写入 AI规划.md §8.2(GBNF 规则名禁下划线 / name-args 需绑定 / 必填卡顿需重试)
- 内置 llama.cpp 完整二进制(AMCL/runtime/llama-cpp,CPU 兜底;有 LM Studio 时可走其 CUDA 后端)

### 🧠 AI 本地模型验证(规划 §8.1)
- **模型选型已拍板**:xLAM 微调版 Qwen3.5-0.8B Q4_K_M 胜出
  (31 条回归测试集 ×3 次贪心解码,LM Studio llama.cpp CUDA:综合 71.8% vs 通用版 51.6%)
- 新增 `model_registry.py`:资源清单 manifest.json + sha256 校验 + 镜像优先下载(hf-mirror → HF)
- 新增 `ai_testset.py`:AI 回归测试集(31 条典型启动器指令 + 期望工具调用,规划 §7.4)
- 评测链路:`.tmp/eval_models.py`(LM Studio API,温度 0 可复现)+ `.tmp/eval_driver.py`
- 模型文件存 `AMCL/models/`(通用版 508.9MB + xLAM 版 504.8MB,均 Q4_K_M,sha256 钉住)

规划中的内容见 [ROADMAP.md](ROADMAP.md):
- 本地推理模块原型(grammar 约束解码先行)
- 配方数据新鲜度提示
- 直接读 mod jar 配方(无需进游戏导出)
- MCP server、AI 崩溃日志分析技能
- bridge-mod 多版本(1.20.1 / 1.21.4)
