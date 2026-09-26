# AMCL v1.0.0

这是 AMCL 的首个正式版本。它把 Minecraft 启动、资源管理和 AI 助手放进同一个窗口；你可以按习惯使用常规模式，也可以进入以对话为主的 AI 模式。

## 下载哪个文件

| 系统 | 文件 | 适合谁 |
| --- | --- | --- |
| Windows | `AgentMinecraftLauncher.exe` | 标准版。单个 exe，首次运行时按需创建旁边的 `AMCL` 文件夹。 |
| Windows | `AgentMinecraftLauncher-Windows-LocalAI.zip` | 想直接使用内置本地模型。解压后运行 exe；包内另有创建桌面快捷方式的脚本。 |
| Linux x86_64 | `AgentMinecraftLauncher-linux-x86_64.tar.gz` | 解压后运行包内程序。 |

Windows 本地 AI 版的快捷方式会记住解压位置；移动文件夹后重新运行 `CreateDesktopShortcut.bat`。macOS 通过了源码测试，目前没有打包文件。

## 从 v0.7.0 升级，你会看到什么

- **两种主界面**：常规模式保留下载、实例和设置入口；AI 模式把对话放在主区域，按实例保存会话，也能创建不关联实例的会话。
- **下载资源更灵活**：Mod、光影包、资源包和数据包可以分别选版本；手动选文件时能看到兼容提示，Beta 版本也可正常选择。
- **实例与联机更顺手**：实例详情和服务端详情共用入口；联机从右侧抽屉打开，不会打断当前页面。关闭抽屉后会恢复 AI 面板原宽度。
- **外观与引导更新**：深浅色由启动器统一控制，自带 Minecraft 壁纸；首次引导支持扫描 API 模型。Linux 标题栏和窗口拖动也做了修正。
- **AI 工具与服务端能力**：AI 可以在得到相应权限和确认后操作实例；服务端管理、日志和导出流程得到扩充。

## 安装与校验

下载本页附件后，用 `SHA256SUMS.txt` 或 `SHA256SUMS-linux.txt` 核对文件。Windows exe 另附 GPG 签名和作者公钥。Windows 包没有商业代码签名证书，系统可能显示未知发布者提示；GPG 签名不能消除此提示。

已有游戏、设置和存档保存在数据目录中。升级前保留原来的 `AMCL` 和游戏目录；替换标准版 exe 时不要删除这些目录。

完整技术变更见 [CHANGELOG.md](CHANGELOG.md)。如果遇到下载或启动问题，可附上脱敏后的启动器日志到 [Issues](https://github.com/erfanyo/Agent_Minecraft_Launcher/issues)。
