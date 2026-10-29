# Agent Minecraft Launcher · AMCL

[下载 v1.2.0](https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/tag/v1.2.0) · [简明更新说明](RELEASE_NOTES_1.2.0.md) · [技术更新日志](CHANGELOG.md) · [构建说明](BUILDING.md)

[![License: GPL-3.0-only](https://img.shields.io/badge/license-GPL--3.0--only-blue.svg)](LICENSE)

**能启动 Minecraft，也能帮你处理 Mod、实例和报错的 AI 启动器。** 常规模式保留完整的启动器操作；AI 模式把会话放在主窗口，两个模式共享实例、下载和设置。

## 1.2.0 正式版

补上身为 MC 启动器的最大短板：CurseForge 正式接入。新增整合包补齐接续、持久缺文件提醒、原包保留和语言包预览；详见 [1.2.0 更新说明](RELEASE_NOTES_1.2.0.md)。

## 下载

| 平台与版本 | 文件 | 使用方法 |
| --- | --- | --- |
| Windows 标准版 | `AgentMinecraftLauncher.exe` | 双击运行；启动器会在旁边按需创建 `AMCL` 数据文件夹。 |
| Linux x86_64 | `AgentMinecraftLauncher-linux-x86_64.tar.gz` | 解压后运行包内的 `AgentMinecraftLauncher`。 |

本轮暂不提供预装本地 AI 模型 ZIP，本地模型功能保留。

安装包与 `SHA256SUMS` 校验文件见 [v1.2.0 Release](https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/tag/v1.2.0)。macOS 已运行源码 CI 测试，当前没有 macOS 安装包。

> 本项目采用 [GNU GPL-3.0-only](LICENSE) 许可。Windows 包没有商业代码签名证书；GPG 签名用于验证来源，不能消除 SmartScreen 提示。

## ✨ 功能一览

### 整合包引导与开放接口（规划）

计划通过游戏内 Mod 与启动器联动，提供结合实际配方、任务进度和资料来源的整合包引导，
以及界面解释、结构投影和分阶段搭建。**1.7.10 Forge、1.12.2 Forge 是必须覆盖的目标版本**，
与现代版本分阶段适配和验收；这不代表上述功能或全部版本现已可用。

同时计划为 **AI 通关 MC 挑战、多 AI 角色协作、玩家像 RTS 一样指挥角色**预留观察、
行动、任务调度、控制权、权限和过程记录接口。这些属于后续可能用法，尚未实现；
详见 [bridge-mod 引导与角色控制扩展规划](bridge-mod/README.md)。

### 🧠 AI 助手(核心特色)
- 停靠式对话面板,内置 **DeepSeek** 配置,也支持 **Ollama / LM Studio** 本地模型
- **工具调用**:AI 能直接操作启动器——
  - 列出/搜索实例与 Mod、读取游戏日志与崩溃报告
  - 安装 Mod、创建实例、备份实例、修改设置
  - 向运行中的游戏发指令(优先走 bridge-mod 本地指令口,精确反馈)
  - 查合成配方(套娃展开)、查按键绑定、生成符合版本语法的游戏指令
- **权限控制**:只读(默认)/ **工作区可写**(可改启动器目录内文件);AI 装 Mod、发游戏指令等写操作需切到工作区可写(切前有确认)。
- **游戏内 AI**:进游戏敲 `/ai` 也能让 AI 问答、发指令(按**游戏类型**判权限:单机/局域网房主允许,连的专用服务器只看 OP)。
- **📌 上下文置顶**:常规模式可把关心的内容"钉"给 AI；AI 模式可引用选中的对话片段并添加注释(上下文操作**不**额外授予执行权限)。
- **技能系统**:崩溃看门狗(自动诊断)、自动重启、备份提醒、指令指南(版本感知)

### 📦 实例管理(PCL2 风格)
- 目录结构 `versions/<实例id>/`,版本隔离,共享 `libraries / assets / runtime`
- 版本树:按大版本分组,含愚人节版本分类、黄金版本 🏅 标记、发布年月
- 创建实例:原版 / **Fabric** / **Forge** / **NeoForge** + Fabric API + 光影 Mod + 优化 Mod(钠/锂等)
- 整合包导入、Mod 启停、运行配置、一键备份(GUI 按钮 + AI 自动备份)

### 🔌 Mod 管理
- Modrinth 中文搜索(如搜"玉"能找到 Jade)、按版本/加载器过滤
- 资源中心支持 Modrinth / CurseForge 混合浏览与独立来源筛选；CurseForge 支持 Mod、整合包、光影、数据包和资源包，整合包导入新实例，数据包安装到选定存档。
- 推荐 Mod 列表、每个 Mod 的版本选择、Mod 卡片二级菜单
- **Mod 依赖网络**:实例管理里一键画出该实例 mod 间的"谁依赖谁 / 谁冲突"(离线解析 jar 元数据,标缺失依赖;力导向图可拖拽缩放)
- **收藏夹**:下载 Mod 时一键收藏(连同所选版本),收藏页按文件夹管理、拖卡片跨夹复制
- **已安装资源卡片**:把某实例已装的 Mod/资源以卡片形式浏览(本地元数据,无需联网)

### 🎮 联机与指令
- **陶瓦跨启动器联机**：浮窗查看大厅信息与成员，自动发现游戏局域网端口；提供美国、上海备用公共节点。已实测 Windows 与 Bazzite 大厅互通及游戏加入，实际连接仍受账号认证、游戏兼容与网络环境影响。
- **联机方案中心**:多方案对比引导(局域网 / 端口转发 / 第三方平台)
- **指令中心**:常用指令模板 + 每个实例自己的指令库
- **bridge-mod 一键配置**(推荐):自制 Mod 提供本地指令口(127.0.0.1:26100)+ 数据导出,命令 100% 精确反馈;RCON(+ Lan Server Properties)为**长期备用通道**,覆盖 bridge-mod 未支持的老版本/非黄金版本

### 📖 配方分析(套娃合成)
- 支持中文直接查(如"终极感应供应器"),自动解析到物品 id
- **完整合成树**:每一层标注用哪台机器/加工设备(工作台 / 冶金灌注机 / 富集仓…)
- **材料总账**:套娃展开到原材料,自动按一炉产出向上取整
- 数据由 bridge-mod 进一次游戏世界自动导出(2891+ 配方),无需装 JEI

### 🎨 界面与体验
- 深色模式、中文/英文界面(自动跟随系统,可手动指定)
- **背景壁纸**(内置渐变/自定义图片)+ 透明磨砂面板、动画过渡,深浅色统一
- **任务管理**:下载/启动等耗时操作统一后台任务(进度、取消、重试),窗口保持可操作
- 实例重命名(同步 id/目录/继承引用)
- 左下角环形下载指示器 + 下载详情
- 命令行 CLI(全部功能可脚本化)

## 🚀 快速开始

1. 在上方表格选择与你的系统对应的包，从 [v1.2.0 Release](https://github.com/erfanyo/Agent_Minecraft_Launcher/releases/tag/v1.2.0) 下载。
2. Windows 标准版直接运行 exe；本地 AI 版先解压 ZIP；Linux 版解压 tar.gz 后运行包内程序。
3. 在首次引导中选好游戏目录和登录方式。AI 可选填 API Key，或使用预装本地 AI 版。

### 下载状态与反馈日志
- 下载详情支持取消和重试。取消在下载分块、解压和 Forge 补丁步骤中生效；正在等待网络响应时需等待响应或超时。重试复用校验通过的文件。
- 整合包导入未完成时保留文件，并暂不列入可启动实例；重新导入同一个压缩包可以继续补齐。CurseForge 清单使用设置中获批的 API Key 下载精确文件版本并校验；Mod、资源包、光影按类型安装。文件下载支持 ForgeCDN 候选地址和 MCIM 镜像回退，镜像请求不携带 API Key；仍失败时显示缺失清单和官方链接，监测下载目录、校验文件后复制到实例并继续安装。
- 支持带完整组件补丁的 MultiMC / Prism 导出包：保留自定义主类、JVM 参数、Tweaker、本地补丁库及 Java 版本要求。缺少组件补丁的包会明确提示，不能按普通 ZIP 当作完整支持。
- 实例改名同步修改 ID、安装目录及同名版本文件，并更新继承引用、保留基础 MC 版本；运行游戏或安装时暂不可改名。启动准备在后台执行，窗口保持可操作。
- 下载成功显示绿色勾，失败显示红色 X；点击下载球可查看原因。网络不稳时会提示“连热点试试？”，拒绝访问、文件不存在、磁盘空间不足等有各自的建议。
- 通用文件下载入口会先尝试首个地址两次，再按下载策略尝试备用源；不代表所有第三方接口都有相同重试次数。
- 新产生的启动器日志、AI 操作记录与云端工具调用训练日志统一脱敏，包括已配置密钥、登录令牌和常见文本凭证。敏感设置的旧值不写进撤销记录。
- 历史日志不会自动清洗；提交 Issues 前仍请检查内容，尤其是旧日志和个人聊天文字。脱敏不能识别所有形式的个人信息。
- 整合包的文件路径会检查目录跳转、Windows 盘符、特殊文件名及链接越界；检测到不安全路径会停止导入。

### Windows 首次运行提示

Windows 单文件程序首次启动会先解压运行组件，可能比后续启动稍慢。

#### ⚠️ 出现「Windows 已保护你的电脑 / 是否保留」提示?
这是 Windows SmartScreen 对**未签名 + 下载量较少**的免费软件的标准确认(不是病毒,只是还没被足够多人运行过),按下面处理即可:

1. 出现蓝色提示 → 点「**更多信息**」→「**仍要运行**」,之后启动器正常打开;
2. 想彻底不再弹:右键 exe → **属性** → 底部勾选「**解除锁定**」→ 确定,一劳永逸;
3. 不放心?用下面的 **SHA256 校验码**核对文件,和发布页一致即未被改动。

> 本项目未购买代码签名证书(个人免费项目),exe 未签名属正常现象;已关闭 UPX 压缩以减少误报。

> **若出现「应用程序控制策略已阻止此文件」**(比上面更严,通常**没有**「仍要运行」按钮):
> 这是 Windows 11 的**智能应用控制(Smart App Control)**在拦未签名的新文件。一次性放行/关闭方法:
> **Windows 安全中心 → 应用和浏览器控制 → 智能应用控制设置 → 关**。
> ⚠️ 部分系统关闭后**不能在设置里重新打开**(除非清理系统或重装),请知悉;这属于本机放行,不是给所有人都能一键过关的办法。

#### 🔍 SHA256 校验码
每次 Release 的 exe 校验码发布在对应 Release 说明里。校验方法(Windows PowerShell):

```powershell
Get-FileHash .\AgentMinecraftLauncher.exe -Algorithm SHA256
```

比对输出与 Release 说明里的哈希,**一致 = 文件完整未被篡改**。

#### 🔏 GPG 签名验证(更强的来源证明)
SHA256 只保证"文件没变",但如果下载渠道被劫持,哈希也能被一起替换。更稳的是用作者的
**GPG 公钥**验证文件确实是作者签名、且未被篡改:

1. **导入作者公钥**(仓库根 `erfanyo.asc`):
   ```powershell
   gpg --import erfanyo.asc
   ```
2. **验证 exe 签名**(每个 Release 附 `AgentMinecraftLauncher.exe.sig`):
   ```powershell
   gpg --verify AgentMinecraftLauncher.exe.sig AgentMinecraftLauncher.exe
   ```
   > 看到 `Good signature from "erfanyo <29330387076@qq.com>"` 即验证通过。

**作者密钥指纹**(核对用,防止公钥本身被调包):
```
D2D1 0D7F 7FC3 E2AF FA76  88E9 1A89 9932 9DC6 5331
```

> 说明:GPG 签名是**来源/完整性证明**(给较真的人),**不能**消除 Windows SmartScreen 的
> "是否保留"提示(那是另一回事,靠代码签名证书/信誉,见上方)。

### 从源码运行(给开发者)

正式打包使用固定依赖和仓库内的构建脚本；见 [BUILDING.md](BUILDING.md)。

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
- 📡 本地 TCP 指令口:发游戏指令 100% 精确反馈(整合 RCON 想实现的能力,不依赖 RCON 协议)
- 📤 数据导出:配方、物品属性、按键绑定 → 供 AI 精确查询
- 一键配置:启动器"运行配置"里一键自动下载安装(离线打 exe 后仍可用;也可从 GitHub Releases 下载)

**bridge-mod 当前状态**:Fabric 1.21.1、Forge 1.16.5(实机验证)/ 1.18.2 / 1.19.2 / 1.20.1 / 1.12.2(已编译待联调)、NeoForge 1.21.1;最新版支持上报「**游戏类型**」供游戏内 AI 智能权限判定。详细状态以 `bridge-mod/RELEASE.md` 为准。

## 🎯 兼容目标

| 加载器 | 状态 |
|---|---|
| Forge | 1.21.1 以下优先适配，旧版走独立兼容实现 |
| Fabric | 1.21.1 以下次优先适配 |
| NeoForge | 1.21.1 以下最后适配；现代版本按各 MC 版本单独发布 |

bridge-mod 的旧版实现不是产品阉割版：会尽量提供完整能力；受旧 API 限制的能力会明确标注，而不是静默消失。

## 📁 项目结构(简述)

```
main.py                  图形界面启动入口
cli.py                   命令行入口
ci_smoke.py              跨平台导入与打包资源检查入口
paths.py                 数据目录与资源路径约定
launcher_app/
  ai/                    AI 对话、模型、工具与路由
  browser/               浏览器桥接、配置与 MCP
  core/                  账号、任务、备份、更新等基础模块
  extensions/            插件接口、网页宿主与技能管理
  features/              随本体发布的正式功能（联机、辅助资源、浏览器等）
  instances/             游戏实例、安装、启动与诊断
  resources/             模组、整合包、下载、导入与配方
  runtime/               Java、进程、内存与系统运行组件
  servers/               服务端安装、运行与导出
  ui/                    界面组件、页面与主题
settings/                设置存储与设置界面
os_platform/             操作系统适配
tests/unit/              单元与功能测试
tests/ui/                界面交互测试
tools/                   构建、验证与维护工具
plugins/                 可选扩展（当前随仓库提供 MCP Server）
plugins_templates/       示例与实验代码，不自动加载
bridge-mod/              Minecraft 桥接 Mod
```

目录约定、完整包名和测试命令见 [源码目录说明](docs/source-layout.md)。
正式能力与插件的边界见 [本体功能说明](docs/builtin-features.md)。

## 🧑‍💻 命令行 CLI

```bash
python cli.py instances
python cli.py mod search 玉 --game-version 1.21.1
python cli.py mod install neoforge-21.1.248 sodium
python cli.py ai "终极感应供应器要多少材料"      # AI 会调配方工具查
python cli.py log neoforge-21.1.248
```

## 🧪 测试基建:本地模型镜像服务器(测试/开发用)

模型文件(约 500MB)测试时走公网(hf-mirror)慢,可用本地服务器秒下:

```bash
# 1) 启动服务器(默认端口 8765,服务 AMCL/models/ 目录)
.venv\Scripts\python.exe -m launcher_app.ai.dev_model_server  # 或指定端口

# 2) 另开终端,设置环境变量后跑启动器/测试 —— 模型下载自动走本地,不走公网
$env:AML_MODEL_MIRROR = "http://127.0.0.1:8765"
python main.py
```

> 更省事的替代(日常推荐):直接把开发机 `AMCL/models/`(模型 + manifest.json)拷到
> 测试环境同路径,sha256 校验通过后 `download()` 直接跳过,零下载。服务器适合反复测
> 下载链路(进度/校验/失败重试)或 Sandbox 里不方便拷大文件的场景。

## 📋 更新日志

玩家版见 [v1.2.0 更新说明](RELEASE_NOTES_1.2.0.md)；完整技术版见 [CHANGELOG.md](CHANGELOG.md)。

## 🔄 自动更新

启动器内置更新检查(**设置 → 系统 → 检查更新**):从 GitHub Releases 拉取最新版本对比,
发现新版可一键下载并自动替换重启;同时显示 bridge-mod 的发布情况。
**发版规范**:AMCL 打 `vX.Y.Z` tag + Release(附 `AgentMinecraftLauncher.exe`);
bridge-mod 单独 tag(如 `v0.1.0`),附 `agentmc-bridge-fabric/neoforge-*.jar` 资产。

## 📜 规划

后续规划见 [规划-汇总.md](规划-汇总.md)(唯一定位文档;历史拆分稿已归档到 `docs/archive/`)。
