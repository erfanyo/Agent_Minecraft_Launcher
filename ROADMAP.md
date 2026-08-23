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

- [ ] **bridge-mod 游戏内 AI 交互入口(日程,未来)**
  - 在 bridge-mod 里提供游戏内 AI 入口(聊天栏/快捷键 → 向启动器提问 → 回显游戏内)
  - 通道由启动器设置 `ai_in_game` 决定:off(不用)/ cloud(走云端,游戏内辅助复杂场景)/ local(本地模型)
  - 启动器侧需要:接收游戏内请求的本地通道(bridge 指令口扩展),后端待定
  - 卸载联动已定:off/cloud 时游戏启动卸载本地模型;local 时常驻(见 AI规划.md §5.1)

- [ ] **D. 配方数据新鲜度**
  - 返回信息里带"数据来自 X 实例、导出于 YYYY-MM-DD HH:MM"(目前 describe_full 头部已有,可再扩展)
  - 换 mod / 重装实例后提示"数据可能过期,建议重新进一次世界导出"
  - 可选:对 recipe 数量做摘要(如"共 2891 个配方,来自 neoforge-21.1.248")

- [ ] **旁路:直接读 mod jar 配方(无需进游戏)**
  - 现状:配方来自 bridge-mod 进游戏导出,需要用户先进一次世界
  - 方案:解析实例 mods 目录里 jar 的 `data/<mod>/recipe/*.json`(datapack 格式,含 shaped pattern+keys、smelting 等),任何已装 mod 无需进游戏即可查
  - 注意:datapack 格式与 bridge 扁平格式不同,需写 shaped 展开解析器;可能被服务端/数据包覆盖(单机无碍)
  - 建议与 bridge 数据做合并:jar 数据为基座,bridge 数据为"实际生效"的覆盖

- [ ] 配方"原料未导出"缺口(bridge 导出器局限)
  - Mekanism 冶金灌注机等特殊配方(metallurgic_infusing)的灌注原料 bridge 未导出 → 树里标"需游戏内确认"
  - 改进方向:bridge-mod 的 RecipeExporter 对特殊配方类型补导出(需重编译 mod),或旁路方案直接读 jar 配方解决

## 🧭 其他候选(用户挑选)

- [ ] MCP server(让外部工具/脚本也能调用启动器能力)
- [ ] AI 崩溃日志分析技能(自动定位崩溃原因)
- [ ] 26.2 实例回归测试
- [ ] bridge-mod 多版本支持(1.20.1 / 1.21.4)
- [ ] Forge(1.19 及以前)加载器支持
- [ ] RconAutoOpener 反射修复(RCON 长期通道的改进:免装 Lan Server Properties 也能自动开 RCON)
- [ ] check_bridge_mod 更新流程接入一键配置
- [ ] **界面模式:新手 / 专家**(老玩家少看提示,新玩家多引导;新手模式显示首页科普/首次引导)
- [ ] **整合包作者辅助**:把启动器做成整合包作者的工具——
      导入/导出/编辑 .mrpack、依赖检查(缺前置自动提示/补齐)、
      本地试装验证、一键打包上传 Modrinth 发布
