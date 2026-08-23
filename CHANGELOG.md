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

规划中的内容见 [ROADMAP.md](ROADMAP.md):
- 配方数据新鲜度提示
- 直接读 mod jar 配方(无需进游戏导出)
- MCP server、AI 崩溃日志分析技能
- bridge-mod 多版本(1.20.1 / 1.21.4)
