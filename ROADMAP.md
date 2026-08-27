# Agent Minecraft Launcher — 项目规划(ROADMAP)

启动器当前状态与后续规划。按优先级排序,条目可勾选。

## ✅ 已完成

- [x] **AI 本地模型选型拍板(§8.1 模型验证)** — 2026-08-23
  - 下载 Qwen3.5-0.8B 通用版 + xLAM 微调版 GGUF(均 Q4_K_M,sha256 校验,存 AMCL/models/ + manifest.json 资源清单)
  - 建回归测试集 `ai_testset.py`(31 条典型指令 + 期望工具调用),走 LM Studio llama.cpp(CUDA)实测
  - 结果:xLAM 微调版胜出(综合 71.8% vs 51.6%),最终模型 = `qwen3.5-0.8b-function-calling-xlam.q4_k_m.gguf`
  - 报告:`.tmp/eval_out/compare.md`;详情见 AI规划.md §8.1

- [x] **配方查询修复 + 套娃展开(A+B+C)** — 2026-08
  - 数据定位:get_recipe_path 支持 `instance` 参数,缺省自动探测所有实例,取最新导出的 `.bridge/recipes.json`(修复"数据已导出却查不到")
  - 完整合成树:brief=false 返回 合成树(每步标注机器/加工设备,如 工作台/冶金灌注机/富集仓)+ 材料总账(展开到原材料,自动按一炉产出向上取整)
  - 中文名索引:从实例 mods 目录的 jar 语言文件(zh_cn.json/en_us.json)构建 中文/英文名 → 物品 id 映射,AI 直接输中文即可查
  - 流程收敛:工具描述写明"查不到就停、告诉用户进一次世界";失败返回带"哪些实例有/缺数据"
  - 验证:.tmp/test_recipe_zh.py 9 项 + 全量回归(18+29+CLI+设置)全 PASS

- [x] **Mod 依赖网络 / 反向依赖(灵感 #4+#5,简单版)** — 2026-08-24
  - `mod_deps.py`:离线解析实例 mods 目录各 jar 元数据(fabric.mod.json / mods.toml),构建依赖图
    (required/optional/incompatible,标出缺失依赖);`mod_graph.py`:QGraphicsView 渲染(力导向/拖拽/滚轮缩放)
  - 入口:实例管理 → Mod 页 →「Mod 依赖网络」(后台解析 + "正在分析依赖关系"进度条)
  - 说明:覆盖本实例已装 mod(离线精准);全网反向依赖(Modrinth 无 dependents API)暂不做
  - 待办:下载 Mod 时按 Modrinth 正向 dependencies 自动提示"需要什么/冲突"(数据已取到,未接 UI)

## 🔜 规划中(按需启用)

- [x] **本地推理模块原型:grammar 约束解码(§8.1 续接②先行项)** — 2026-08-23
  - `local_ai.py` GrammarToolEngine:从工具 schema 自动生成 GBNF(工具分支绑定 + required 强制)
  - 自带 llama.cpp server(b10590)加载 xLAM Q4_K_M,实测结构 100% 合法 JSON
  - 效果:31 条测试集 ×3 次平均,参数准确率 79.0% vs 原生 tools 69.4%(+9.6%);详见 AI规划.md §8.2
  - 踩坑已记录:GBNF 规则名禁下划线、name-args 需绑定、必填卡顿自动重试

- [x] **任务路由与失败链路(§1 落地)** — 2026-08-23
  - `task_router.py`:难度判定(诊断/代码/规划=难,翻译/摘要/分类=易)+ FAQ 规则引擎 + 失败链路
  - 优先级:工具动词→本地 / 纯问答→规则 / 困难→云端 / 歧义→ask / 未知→云端兜底
  - `run_with_fallback`:本地 → 规则 → 云端 → 诚实认输,端到端联调验证通过
  - schema 单一来源:`local_ai` 从 `assistant.TOOLS` 自动生成 GBNF,新增工具只改 assistant.py 一处

- [x] **§8.1 已知问题修复** — 2026-08-23
  - ask_user 触发不灵 → 路由层架构级兜底(歧义请求直接构造 ask_user,不依赖 0.8B 模型自觉)
  - compare_items 英文参数 → 描述强化 + recipe_graph 英文别名映射(大小写/空格容错)
  - 启动实例误解 → install_instance(创建)/launch_game(启动)描述区分,本地云端同步
  - 修复后 grammar 全量回归 78.5%,无回归

- [x] **本地推理模块接入启动器全链路** — 2026-08-23
  - ✅ 前端:设置 `local_builtin` provider(W1)/ 多模态按模型自动隐藏(W2)/ 聊天循环接入路由(W3)/
    后台自动下载+进度(W4)/ 游戏内 AI 通道 `ai_in_game` + 启动联动(W7)
  - ✅ 后端:真实上下文注入(§7.3,B3,73.9% vs 66.9%)/ 回归入口 `--regress`(B5)/
    续写重试修必填卡顿;端到端冒烟通过
  - 任务书已归档(`_agent_comms/任务书-本地模型前端接入.md`),后续跳过
  - 全部完成:W5 引导提示(c0a4943)/ W6 推理状态 + 游戏启动避让(c0a4943)/ 冷启动预热(037af38)

- [x] **指令通道职责勘误(2026-08-23)**
  - **bridge-mod 不负责开启 RCON**——内部已整合指令口功能(本地 TCP 指令口 + CommandSource 精确反馈)
  - RCON(+ Lan Server Properties + 模拟按键)定位为**长期备用通道**,服务 bridge-mod 未覆盖的
    老版本/非黄金版本(详见项目规划.md 灵感 #10 勘误;game_command.py 通道:bridge → RCON → 模拟按键)

- [x] **下一版目标(2026-08-24,用户指定)**
  - **资源中心 Mod 列表默认自动加载** ✅ 2026-08-26:切到资源浏览器页且搜索框为空 → 自动默认浏览(`maybe_auto_load`
    在 `switch_to` 调用,已加载过则不重复拉取,不覆盖用户已输关键词)
  - **Mod 中文名翻译对照表**(PCL2 `WikiEntries.txt` 合并):**未做** —— `mod_cn.py` 现为人工 curated(70+)+
    `mod_cn_ext.json` 扩展(Modrinth Top-N + 人工通译);PCL2 开源库合并待评估 LICENSE/**暂缓**

- [ ] **发版更新日志两版(2026-08-24 定)** — 打包/发布时必须同时出:① 完整技术版 changelog(现有
  `CHANGELOG.md` 风格,给开发者,含模块/commit 信息)② 「摘要」版(名义摘要、实际要求**新手能看懂**:
  大白话讲"这次更新能干嘛/对用户有啥用",不堆技术黑话,面向普通玩家/朋友)。Release / README 面向用户用摘要版。

- [x] **bridge-mod 游戏内 AI 交互入口** ✅ 2026-08-26(launcher 侧 + mod 侧 /ai 已通)
  - mod 侧:`/ai <内容>` 写 `.bridge/ai_request.json` → 轮询 ai_reply.json → 回显 `[AI] …`(AiChat)
  - launcher 侧:`in_game_ai.py` `InGameAI` 轮询 + `make_answerer`(按 `ai_in_game` 路由,带指令工具)实测通过
  - 通道由 `ai_in_game` 决定;卸载联动同 §5.1 —— **核心已做,后续细化**(如给 mod 补 /ai 用法提示等)

- [ ] **D. 配方数据新鲜度**
  - 返回信息里带"数据来自 X 实例、导出于 YYYY-MM-DD HH:MM"(目前 describe_full 头部已有,可再扩展)
  - 换 mod / 重装实例后提示"数据可能过期,建议重新进一次世界导出"
  - 可选:对 recipe 数量做摘要(如"共 2891 个配方,来自 neoforge-21.1.248")

- [x] **旁路:直接读 mod jar 配方(无需进游戏)** — 2026-08-23 ✅
  - 现状:配方来自 bridge-mod 进游戏导出,需要用户先进一次世界
  - 方案:解析实例 mods 目录里 jar 的 `data/<mod>/recipe/*.json`(datapack 格式,含 shaped pattern+keys、smelting 等),任何已装 mod 无需进游戏即可查
  - 注意:datapack 格式与 bridge 扁平格式不同,需写 shaped 展开解析器;可能被服务端/数据包覆盖(单机无碍)
  - 建议与 bridge 数据做合并:jar 数据为基座,bridge 数据为"实际生效"的覆盖
  - 落地:`recipe_datapack.py`(解析/合并/缓存到 AMCL/cache/recipes-jar)+ `recipe_graph.load_recipe_data`;6 条验收 PASS(见 `_agent_comms/提示词-配方旁路.md` §6)

- [x] 配方"原料未导出"缺口(bridge 导出器局限) — 2026-08-23(旁路已部分解决)
  - Mekanism 冶金灌注机等特殊配方(metallurgic_infusing)的灌注原料 bridge 未导出 → 树里标"需游戏内确认"
  - 改进方向:bridge-mod 的 RecipeExporter 对特殊配方类型补导出(需重编译 mod),或旁路方案直接读 jar 配方解决
  - 落地:旁路能读到特殊配方时直接补上原料(同 id 空原料用 jar 补齐);读不到(纯代码配方)仍保留"需游戏内确认"标注

## 🧭 其他候选(用户挑选)

- [ ] MCP server(让外部工具/脚本也能调用启动器能力)
- [x] **崩溃分析与修改意见(进阶):修改意见清单 ✅ + 自主修复回路 ✅ 2026-08-26**
  - ✅ 分析层**已具备**:`read_instance_log` / `read_crash_report` 工具(AI 可读日志/崩溃报告)+
    云端深度诊断 + 游戏异常退出自动抓日志/崩溃报告问 AI(`main.py`)
  - ✅ ① **分析结果 → 结构化"修改意见"清单**:技能「崩溃诊断·修改意见清单」(每条=改什么+为什么/怎么做,按严重度+兜底);
    诊断触发已修复(退出码非0 / 本次新崩溃报告 / 日志含崩溃标记)
  - ✅ ② **权限内自主修复回路**:技能「崩溃诊断·自主修复回路」——诊断后对**可自动修复项**
    (改内存 set_setting / 重装冲突 Mod install_mod / 备份 backup_instance / 建新实例)在**用户同意 + 工作区可写**
    时直接动手并验证;硬件/驱动/删存档等不可自动项明确说明不硬来。
    **改不了 → 回到修改意见清单 / 升级云端深度诊断**。
  - 配套:云端工具挂载加 `crashrepair` 组(崩溃/诊断关键词命中→挂上 install_mod/install_mods/set_setting/
    backup_instance/install_instance 写工具),CLOUD_MAX_TOOLS 10→14;工具执行器按 ai_actions 权限校验
    (readonly 拒写 / workspace_write 放行,已实测)。
- [ ] 26.2 实例回归测试
- [x] bridge-mod 多版本支持(1.20.1 / 1.21.4) — **1.20.1(fabric+forge)✅ 实测**;1.21.4 **未做**
  (当前已覆盖: fabric 1.20.1/1.21.1、forge 1.20.1、neoforge 1.21.1;1.21.4 待补)
- [ ] Forge(1.19 及以前)加载器支持
- [ ] **微软正版登录 AADSTS700016 修复(测试受阻,等正式版)** — 2026-08-26
  - **现象**:点「微软正版登录」报 `HTTP 400` / `unauthorized_client` /
    `AADSTS700016: Application with identifier '00000000402b5328' was not found in the directory '9188040d-…'`。
  - **根因(已实测确认)**:`microsoft_auth.py` 用的 Mojang 旧公开 client_id `00000000402b5328`(以及 azalea/社区
    的 `00000000441cc96b`)、`/consumers` 端点,均在消费租户 `9188040d-6c67-4c5c-b112-36a304b66dad` 中查不到该应用;
    `/common`、`/organizations` 端点分别报 no-tenant / multiple-resource。→ **不是 client_id 写错,是微软已回收
    这些 Minecraft 公开 client_id 在该租户的可用性**(2025 后对第三方启动器收紧,要求自注册 Azure AD 应用;
    社区见 PrismLauncher #3300 "Cannot add microsoft account"、"Invalid app registration"、D-U-N-S 讨论)。
  - **修复方案(需用户操作,待定)**:在 Azure portal 免费注册一个**个人 Azure AD 应用**拿到自己的
    `client_id`(允许 public client flow / 设备码流,scope 用 `service::user.auth.xboxlive.com::MSCS`),
    替换 `microsoft_auth.py` 的 `_CLIENT_ID`。这是个一次性手工步骤,我无法代注册。
  - 备选/进一步确认:是否需要 `XboxLive.signin` Azure 权限(Microsoft Q&A 有专门讨论),以及 D-U-N-S/企业验证
    是否强制(社区两种说法都有)。**做成「设置里可填自定义 Azure 应用 client_id」最稳妥**,避免硬编码。
- [x] RconAutoOpener 反射修正 ✅ 2026-08-26(Forge 1.20.1 单参 `RconThread.create(ServerInterface)`(srg m_11615_);实测确认**专用服务器 vanilla 已自行开 RCON**,故改为识别并跳过,消除失真报错)
- [x] check_bridge_mod 更新流程接入一键配置 ✅ 2026-08-26(一键配置 bridge-mod 区分 not_installed/outdated/up_to_date;旧版提示更新、一键覆盖)
- [ ] ask_user 回归用例排查(ask_01/ask_02 持续 0 分,历史问题;t8/t12 评审均记录)
- [ ] route_by_model 评审结果短时缓存(P2/P3 优化,减少重复本地推理)
- [~] **界面模式:全面 / 摘要**(原"新手/专家",2026-08-24 初步落地:设置→界面;全面=显示资源科普/详细提示,摘要=隐藏科普/精简。**规范:以后任何 UI 改动都要适配两种模式**;对外不叫"新手/专家",免得显得看不起新手)
- [ ] **整合包作者辅助**:把启动器做成整合包作者的工具——
      导入/导出/编辑 .mrpack、依赖检查(缺前置自动提示/补齐)、
      本地试装验证、一键打包上传 Modrinth 发布
- [ ] **发版时跑完整 GPG 打包流程(build_release.ps1)** — 2026-08-28
  - GPG 签名已集成(见 commit a196158),但**完整"打包+签名"端到端未跑过**(只单独验证了签名命令)。
  - **下次发版时**在项目根运行 `.\build_release.ps1`(需 gpg 已在 PATH / 便携版 `D:\programs\Git` 之外,
    用独立 GnuPG 2.5.x),确认:PyInstaller 打包 → 对 exe 生成 `.sig` → SHA256;
    产物附 release:`AgentMinecraftLauncher.exe` + `.sig` + `erfanyo.asc`。
  - 前提:gpg bin 已在用户 PATH;密钥 erfanyo(ed25519,无口令)已生成,指纹
    `D2D1 0D7F 7FC3 E2AF FA76  88E9 1A89 9932 9DC6 5331`。
