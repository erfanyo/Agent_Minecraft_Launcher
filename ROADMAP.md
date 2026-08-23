# Agent Minecraft Launcher — 项目规划(ROADMAP)

启动器当前状态与后续规划。按优先级排序,条目可勾选。

## ✅ 已完成

- [x] **配方查询修复 + 套娃展开(A+B+C)** — 2026-08
  - 数据定位:get_recipe_path 支持 `instance` 参数,缺省自动探测所有实例,取最新导出的 `.bridge/recipes.json`(修复"数据已导出却查不到")
  - 完整合成树:brief=false 返回 合成树(每步标注机器/加工设备,如 工作台/冶金灌注机/富集仓)+ 材料总账(展开到原材料,自动按一炉产出向上取整)
  - 中文名索引:从实例 mods 目录的 jar 语言文件(zh_cn.json/en_us.json)构建 中文/英文名 → 物品 id 映射,AI 直接输中文即可查
  - 流程收敛:工具描述写明"查不到就停、告诉用户进一次世界";失败返回带"哪些实例有/缺数据"
  - 验证:.tmp/test_recipe_zh.py 9 项 + 全量回归(18+29+CLI+设置)全 PASS

## 🔜 规划中(按需启用)

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
- [ ] RconAutoOpener 反射修复
- [ ] check_bridge_mod 更新流程接入一键配置
- [ ] **界面模式:新手 / 专家**(老玩家少看提示,新玩家多引导;新手模式显示首页科普/首次引导)
- [ ] **整合包作者辅助**:把启动器做成整合包作者的工具——
      导入/导出/编辑 .mrpack、依赖检查(缺前置自动提示/补齐)、
      本地试装验证、一键打包上传 Modrinth 发布
