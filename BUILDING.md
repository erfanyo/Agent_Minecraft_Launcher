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
- Windows 手动任务：使用 Python 3.14.7 构建单文件 exe，并实际启动成品验证内置资源。

打包任务只在手动触发 CI 时运行；日常提交仍运行三平台加载检查和完整自动测试。这样既不
隐藏现有打包问题，也不会让尚未解决的第三方冻结问题阻塞普通开发。

目前 CI 下载并校验的是已发布的四个 bridge-mod 包。本地 `bridge-mod/dist` 中尚未发布的
其他版本不会自动进入 CI 成品；发布这些包并把地址和校验值加入
`tools/fetch_bridge_mod_jars.py` 后，CI 才能稳定包含它们。

WSL 的准备、自动测试和 WSLg 界面测试见 `WSL_TESTING.md`。
