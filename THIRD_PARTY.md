# 第三方组件许可声明 (THIRD-PARTY NOTICES)

本启动器内嵌/分发的第三方组件及其许可如下。分发时请保留本说明,遵守各组件许可。

## 1. llama.cpp (运行库 / 本地推理引擎)
- 版本:  b10590 (GitHub Release tag)
- 来源:  https://github.com/ggml-org/llama.cpp/releases/tag/b10590
- 下载:  官方预编译二进制,按平台/架构(见 `tools/fetch_llamacpp.py`)
  - Windows x64/arm64: `llama-b10590-bin-win-cpu-<arch>.zip`
  - macOS x64/arm64:   `llama-b10590-bin-macos-<arch>.tar.gz`
  - Linux x64/arm64:   `llama-b10590-bin-ubuntu-<arch>.tar.gz`
- 许可:  **MIT**(llama.cpp 本身,版权 Georgi Gerganov 及贡献者)
  - 文本见 https://github.com/ggml-org/llama.cpp/blob/master/LICENSE
- 第三方附带: LLVM OpenMP runtime(许可见运行时目录 `LICENSE-LLVM-OpenMP`)。

## 2. 内置本地模型 (Qwen3.5-0.8B 系列 GGUF)
- Qwen3.5-0.8B 通用版 / Qwen3.5-0.8B Function-Calling(xLAM) 微调版
- 来源:  Hugging Face(GGUF 量化版)
- 许可:  **Apache-2.0**
  - 详见 https://huggingface.co/Qwen/Qwen3.5-0.8B(基座原模型许可)
- 说明:  Apache-2.0 允许自由使用/复制/修改/再分发(含商用),分发时保留许可声明即可。

## 3. 其它
- `erfanyo.asc`: 作者 GPG 公钥(见仓库根,用于 exe 签名验证)。
- 更多(如 PySide6/Qt、requests 等 Python 依赖)随其各自许可,见 requirements 对应上游。

---
如需核对内嵌二进制未被篡改:
- llama.cpp 随启动器 exe 打包,exe 由作者 GPG 签名(见 `erfanyo.asc` / `build_release.ps1`),
  任意对二进制的改动都会使 exe 签名失效。
