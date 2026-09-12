# 构建与发布

Windows 是当前正式发布平台。发布环境使用 **Python 3.12.x** 和
`requirements-release.txt` 中锁定的依赖版本。Python 3.14 虽能完成 PyInstaller 打包，
但不能据此判断 exe 可以启动。

当前 PySide6 6.11.2 与 PyInstaller 6.22.2 在本机生成的冻结包会在加载 QtCore 时失败，
最小目录包也能复现。2026-09-02 的 DSH 构建只检查进程是否仍存在，错误弹窗也会让该
检查通过，所以旧记录不能作为可运行证明。正式发布前需由 DSH 调整构建工具版本，并以
本文件中的真实启动检查为准。

## 首次准备

```powershell
py -3.12 -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r requirements-release.txt
```

## 本地验证包

```powershell
.\build_release.ps1 -NoSign
```

脚本会依次运行完整测试、准备并校验 llama.cpp 与 bridge-mod、构建 exe、实际启动成品做
无界面检查，并生成 `dist/SHA256SUMS.txt`。任何一步失败都不会被当成可发布结果。

## 正式签名包

```powershell
.\build_release.ps1
```

此流程还会调用本机 GPG 私钥，生成 `AgentMinecraftLauncher.exe.sig`。CI 没有私钥，
只生成经过启动检查的未签名测试包；正式对外发布仍由本机执行签名。

## CI 覆盖范围

- Windows、macOS、Linux：源码导入检查。
- Windows：完整自动测试和 Python 文件编译检查。
- Windows 手动任务：使用 Python 3.12 构建单文件 exe，并实际启动成品验证内置资源。

打包任务只在手动触发 CI 时运行；日常提交仍运行三平台加载检查和完整自动测试。这样既不
隐藏现有打包问题，也不会让尚未解决的第三方冻结问题阻塞普通开发。

目前 CI 下载并校验的是已发布的四个 bridge-mod 包。本地 `bridge-mod/dist` 中尚未发布的
其他版本不会自动进入 CI 成品；发布这些包并把地址和校验值加入
`tools/fetch_bridge_mod_jars.py` 后，CI 才能稳定包含它们。
