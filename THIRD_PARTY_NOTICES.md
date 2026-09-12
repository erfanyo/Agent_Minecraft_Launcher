# 第三方组件鸣谢

Agent Minecraft Launcher 感谢以下开源项目及服务。此清单记录启动器直接使用、随发行包提供或按需下载的主要组件；各组件仍受其原许可证约束。

| 项目 | 用途与接入方式 | 许可证 |
| --- | --- | --- |
| [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/) | 随程序运行；桌面界面 | [LGPL-3.0 / GPL-3.0 / 商业许可](https://doc.qt.io/qtforpython-6/licenses.html) |
| [Requests](https://github.com/psf/requests) | 随程序运行；网络请求 | [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE) |
| [psutil](https://github.com/giampaolo/psutil) | 随程序运行；内存与进程检测 | [BSD-3-Clause](https://github.com/giampaolo/psutil/blob/master/LICENSE) |
| [cryptography](https://github.com/pyca/cryptography) | 可选功能；插件 Ed25519 签名验证 | [Apache-2.0 或 BSD](https://github.com/pyca/cryptography/blob/main/LICENSE) |
| [pywebview](https://github.com/r0x0r/pywebview) | 可选界面；使用系统 WebView | [BSD-3-Clause](https://github.com/r0x0r/pywebview/blob/master/LICENSE) |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | 本地 AI 运行时；随支持本地 AI 的发行包提供 | [MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) |
| [Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | 按需下载；本地 AI 基础模型 | [Apache-2.0](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/LICENSE) |
| [EasyTier](https://github.com/EasyTier/EasyTier) | 按需下载；虚拟局域网联机 | [LGPL-3.0](https://github.com/EasyTier/EasyTier/blob/main/LICENSE) |
| [PyInstaller](https://pyinstaller.org/) | 仅用于构建 Windows 发行包 | [GPL-2.0-or-later，含启动器例外](https://pyinstaller.org/en/stable/license.html) |

## 外部服务

- [Modrinth](https://modrinth.com/)：提供 Mod、整合包、资源包等资源的检索与下载接口。
- [BMCLAPI](https://bmclapidoc.bangbang93.com/)：按用户的镜像策略提供 Minecraft 文件下载加速。

外部服务由各自运营方独立提供；启动器会根据用户操作与下载策略访问它们。
