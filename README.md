# Agent Minecraft Launcher 🤖⛏️

**AI 助手型 Minecraft 启动器**——不只下载、启动游戏，还能跟 AI 聊天，让 AI 帮你装 Mod、查合成配方、发游戏指令、诊断崩溃日志。

> ⚠️ **测试阶段声明**:本启动器目前处于**测试阶段**,功能迭代频繁、可能有 bug,
> 建议开发者/尝鲜者使用。**正版登录**计划在正式版(v1.0)加入;当前仅**离线模式**(无需正版账号即可启动游戏)。

## ✨ 功能一览

### 🧠 AI 助手(核心特色)
- 停靠式对话面板,内置 **DeepSeek** 配置,也支持 **Ollama / LM Studio** 本地模型
- **工具调用**:AI 能直接操作启动器——
  - 列出/搜索实例与 Mod、读取游戏日志与崩溃报告
  - 安装 Mod、创建实例、备份实例、修改设置
  - 向运行中的游戏发指令(优先走 bridge-mod 本地指令口,精确反馈)
  - 查合成配方(套娃展开)、查按键绑定、生成符合版本语法的游戏指令
- **权限控制**:只读 / 工作区可写 两档,写操作需你授权
- **技能系统**:崩溃看门狗(自动诊断)、自动重启、备份提醒、指令指南(版本感知)

### 📦 实例管理(PCL2 风格)
- 目录结构 `versions/<实例id>/`,版本隔离,共享 `libraries / assets / runtime`
- 版本树:按大版本分组,含愚人节版本分类、黄金版本 🏅 标记、发布年月
- 创建实例:原版 / **Fabric** / **Forge** / **NeoForge** + Fabric API + 光影 Mod + 优化 Mod(钠/锂等)
- 整合包导入、Mod 启停、运行配置、一键备份(GUI 按钮 + AI 自动备份)

### 🔌 Mod 管理
- Modrinth 中文搜索(如搜"玉"能找到 Jade)、按版本/加载器过滤
- 推荐 Mod 列表、每个 Mod 的版本选择、Mod 卡片二级菜单

### 🎮 联机与指令
- **联机方案中心**:多方案对比引导(局域网 / 端口转发 / 第三方平台)
- **指令中心**:常用指令模板 + 每个实例自己的指令库
- **bridge-mod 一键配置**(推荐):自制 Mod 提供本地指令口(127.0.0.1:26100)+ 数据导出,命令 100% 精确反馈;RCON 为临时备用方案

### 📖 配方分析(套娃合成)
- 支持中文直接查(如"终极感应供应器"),自动解析到物品 id
- **完整合成树**:每一层标注用哪台机器/加工设备(工作台 / 冶金灌注机 / 富集仓…)
- **材料总账**:套娃展开到原材料,自动按一炉产出向上取整
- 数据由 bridge-mod 进一次游戏世界自动导出(2891+ 配方),无需装 JEI

### 🎨 界面与体验
- 深色模式、中文/英文界面(自动跟随系统,可手动指定)
- 左下角环形下载指示器 + 下载详情
- 命令行 CLI(全部功能可脚本化)

## 🚀 快速开始

### 方式一:直接运行 exe(给朋友/普通用户)
- 从 [GitHub Releases](https://github.com/erfanyo/Agent_Minecraft_Launcher/releases) 下载
  **AgentMinecraftLauncher.exe**(Windows,无需安装 Python),双击即用
- 或开发机自己打包:
```bash
# 开发机打包(一次性)
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AgentMinecraftLauncher main.py
# 产物:dist\AgentMinecraftLauncher.exe,直接拷给朋友即可
```
> 提示:exe 会把游戏目录 `.minecraft` 建在**自己旁边**;首次启动稍慢(单文件自解压)属正常;
> Windows Defender 可能误报 PyInstaller 单文件 exe,分发时请朋友"添加信任"。

### 方式二:从源码运行(给开发者)
```bash
python -m venv .venv            # 创建虚拟环境
.venv\Scripts\Activate.ps1      # 激活(Windows)
pip install -r requirements.txt
python main.py
```

## 🤖 配置 AI

启动器内打开 **设置 → AI** 或点 AI 面板的设置:

| 提供方 | 说明 |
|---|---|
| **DeepSeek(默认)** | 填 API Key 即用,便宜好用 |
| **Ollama**(本地) | `http://localhost:11434/v1`,模型如 `qwen2.5:7b` |
| **LM Studio**(本地) | `http://localhost:1234/v1`,选一个已加载模型 |

AI 权限默认**只读**(可查不可改),需要 AI 帮你装 Mod/发指令时,在 AI 面板切换为"工作区可写"。

## 🔌 bridge-mod(推荐安装)

自制 Mod,给启动器提供**游戏内数据与指令通道**:
- 📡 本地 TCP 指令口:发游戏指令 100% 精确反馈(替代 RCON 的"盲发")
- 📤 数据导出:配方、物品属性、按键绑定 → 供 AI 精确查询
- 一键配置:启动器"运行配置"里一键自动下载安装(离线打 exe 后仍可用;也可从 GitHub Releases 下载)

**当前支持**:Fabric / NeoForge · MC **1.21.1**(1.20.1 / 1.21.4 适配中)

## 🎯 兼容目标

| 加载器 | 状态 |
|---|---|
| Fabric | ✅ 全部版本 |
| NeoForge | ✅ 全部版本 |
| Forge | 🕐 1.19 及以前晚点再做(优先 mod 活跃版本) |

优先适配 mod 活跃/多的版本:**1.21.1**(已实测 ✅)→ 1.20.1 / 1.21.4(目标中)。

## 📁 项目结构(简述)

```
main.py              主窗口(AI 面板 / 版本树 / 下载 / Mod)
download_tab.py      下载新实例向导
instance_manager.py  实例管理 / 运行配置 / 备份
recipe_graph.py      配方分析(套娃合成树 + 中文索引)
agent_tools.py       AI 工具层(文本进→文本出,CLI 与 AI 共用)
assistant.py         AI 对话 + 工具调用 + 权限
bridge_mod_dist.py   bridge-mod 分发(离线打 exe / 在线 GitHub)
bridge-mod/          自制 Mod 源码(MultiLoader:fabric + neoforge)
cli.py               命令行入口
```

## 🧑‍💻 命令行 CLI

```bash
python cli.py instances
python cli.py mod search 玉 --game-version 1.21.1
python cli.py mod install neoforge-21.1.248 sodium
python cli.py ai "终极感应供应器要多少材料"      # AI 会调配方工具查
python cli.py log neoforge-21.1.248
```

## 📋 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 📜 规划

后续规划见 [ROADMAP.md](ROADMAP.md)(配方数据新鲜度、直接读 mod jar 配方、MCP server、崩溃日志分析技能等)。
