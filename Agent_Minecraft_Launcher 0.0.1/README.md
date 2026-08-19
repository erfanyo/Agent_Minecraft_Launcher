# Agent Minecraft Launcher

AI 助手型 Minecraft 启动器。完整规划见 [项目规划.md](项目规划.md)。

## 环境准备(阶段 0,一次性)

**先懂一个概念**:Python 有"全局环境"和"项目专属环境"。每个项目建一个专属环境(叫 **venv 虚拟环境**),这样 A 项目装的东西不会影响 B 项目。这是 Python 项目管理的入门第一课,很简单。

1. **安装 Python**(只装一个版本就够)
   - 到 <https://www.python.org/downloads/> 下载 **Python 3.11 或更新版本**
   - 安装时**务必勾选** "Add Python to PATH"
   - 命令行输入 `python --version`,能显示版本号即成功

2. **创建项目专属虚拟环境**(在项目目录下执行)
   ```
   python -m venv .venv
   ```

3. **激活虚拟环境**(以后每次在这个项目干活,第一步都是激活它)
   ```
   .venv\Scripts\Activate.ps1
   ```
   - 看到命令行开头出现 `(.venv)` 即成功
   - 若报"禁止运行脚本":先执行 `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`,然后重开终端再激活

4. **安装依赖**(装进虚拟环境,不碰系统)
   ```
   pip install -r requirements.txt
   ```

5. **运行起步程序**
   ```
   python main.py
   ```
   - 看到弹出"你好!我是 Agent 启动器 🤖"窗口即成功 ✅

> **日常工作流**:打开终端 → `cd` 到项目目录 → 激活 `.venv` → `python main.py`

## 常见问题:多个 Python 版本怎么管?

**现在别装多个版本!** 这个项目只需要一个 Python。多版本管理是"将来同时维护多个项目"才需要的:

| 工具 | 管什么 | 说明 |
|---|---|---|
| venv(Python 内置) | 每个项目的依赖隔离 | 必须会,上面已经用了 |
| pyenv-win | 安装/切换多个 Python 版本 | 将来需要时再装 |
| uv | 版本+依赖一起管,超快 | 新兴工具,可作长期选择 |
| conda | 版本+依赖+科学计算库 | 数据科学常用,对我们是杀鸡用牛刀 |

## 当前进度

- [x] 方向、技术栈、AI 方案已定(见项目规划.md)
- [x] 阶段 0:环境准备 ✅
- [x] 阶段 1:启动器核心(版本列表 → 下载 → 启动 ✅ 能离线启动游戏)
- [ ] 阶段 2:AI 助手(对话 + 崩溃日志分析)
- [x] 阶段 3:Mod 管理(实例向导 ✅ 加载器 Fabric/Forge/NeoForge ✅ Modrinth 搜索下载 ✅)
- [ ] 阶段 5:打包发布(exe)
