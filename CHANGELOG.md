# 更新日志(CHANGELOG)

本启动器采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。
版本号遵循语义化版本:[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。

> 说明:早期开发历史在本地重装系统时丢失,故 v0.2.0 起汇总记录全部已实现功能,
> 后续版本只记录增量。

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
  多模态按 provider 自动预设(local_builtin→关 / openrouter→开,可覆盖);
  新增 `ai_in_game` 下拉(off/cloud/local),游戏启动时 off/cloud 卸载本地模型、local 保留;
  窗口关闭卸载本地模型,无残留 llama-server 进程
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
