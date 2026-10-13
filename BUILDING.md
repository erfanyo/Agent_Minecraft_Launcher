# 构建与发布

Windows 是当前正式发布平台。发布环境固定使用 **Python 3.14.7** 和
`requirements-release.txt` 中锁定的依赖版本。`v0.7.0` 已用这套组合生成可启动的
单文件程序；正式发布仍必须通过本文件中的成品启动检查，不能只判断进程是否仍存在。

重装系统后，旧 `.venv` 可能仍在，但它引用的基础 Python 已被删除。这时运行
`.venv\Scripts\python.exe --version` 就会失败，应重新安装 Python 3.14.7 并重建环境，
不要把残留的 `.venv` 当作完整环境。

发布脚本会隔离构建时的外部动态库搜索路径；打包规则也会拒绝从 Poppler 等开发工具
目录误收的同名 ICU 库。否则这些库可能覆盖 Windows 自带组件，造成成品导入 QtCore
失败，但源码运行仍然正常的假象。

## 首次准备

```powershell
py install 3.14.7
py -V:3.14 -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r requirements-release.txt
```

## 本地验证包

```powershell
.\build_release.ps1 -NoSign
```

脚本会依次运行完整测试、准备并校验 llama.cpp 与 bridge-mod、构建 exe、实际启动成品做
无界面检查，并生成两个 Windows 版本及 `dist/SHA256SUMS.txt`。本地 AI ZIP 会自动下载
并 SHA256 校验内置模型；因此首次构建这个变体需要额外下载约 530 MB。

Windows 发布有两个变体：

- `AgentMinecraftLauncher.exe`：标准版，单文件；首次运行时由启动器在 exe 旁创建 `AMCL`。
- `AgentMinecraftLauncher-Windows-LocalAI.zip`：解压后包含 exe、`AMCL/models/` 下已校验的
  内置模型，以及 `CreateDesktopShortcut.bat`。运行 BAT 会在桌面创建快捷方式。快捷方式指向
  解压目录的绝对位置；移动目录后再次运行 BAT 更新快捷方式。压缩包只包含这个模型文件，
  不打包开发机的配置、密钥或其他 AMCL 内容。

Windows 构建流程和包内路径约定记录在本文档，后续参与项目的 agent 应先读本节和
[`DISTRIBUTION.md`](DISTRIBUTION.md) 及 `tools/build_local_ai_bundle.py`，然后再改发布流程。

## 正式签名包

```powershell
.\build_release.ps1
```

此流程还会调用本机 GPG 私钥，生成 `AgentMinecraftLauncher.exe.sig`。CI 没有私钥，
只生成经过启动检查的未签名测试包；正式对外发布仍由本机执行签名。

## CI 覆盖范围

- Windows、macOS、Linux：源码导入检查。
- Windows、macOS、Linux：完整自动测试、Python 文件编译检查，以及普通/150% 缩放的 Qt UI 自动化。
- Windows 手动任务：使用 Python 3.14.7 构建单文件 exe 和预装本地 AI ZIP，并实际启动
  标准版成品验证内置资源；模型由包生成脚本单独校验。
- Linux 手动任务：在 Ubuntu 22.04 上构建 `onedir`，实际启动成品验证内置资源，
  然后上传 `AgentMinecraftLauncher-linux-x86_64.tar.gz` 和 SHA256 文件。

打包任务只在手动触发 CI 时运行；日常提交仍运行三平台加载检查和完整自动测试。这样既不
隐藏现有打包问题，也不会让尚未解决的第三方冻结问题阻塞普通开发。

BridgeMod 发布输入固定在 `bridge-mod/prebuilt/manifest.json`：0.2.0 共八个 JAR，
随源码保存，以 SHA256 校验。准备脚本将它们原子复制到 `bridge-mod/dist`，
不依赖旧 GitHub Release 的四个包；预检会拒绝遗漏、损坏或清单外的 JAR。
更新桥接源码时，须重新编译对应 JAR、更新 prebuilt 文件与清单，并重新验证。
运行时历史在线下载兜底与 CI 固定构建输入分开管理。

WSL 的准备、自动测试和 WSLg 界面测试见 `WSL_TESTING.md`。

Linux 测试包也可在 Linux 环境中运行 `bash tools/build_linux.sh` 构建。正式 Linux
兼容包以 CI 的 Ubuntu 22.04 产物为准；不要使用较新的本地发行版替代正式构建环境。
