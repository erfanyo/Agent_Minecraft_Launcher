# 决策模型（System One / decision model）调研小结：Kev 与 Laya

> 目标：评估 Kev 与 Laya 能否集成进一个**离线本地**的 Minecraft 启动器 AI 助手（已用 llama.cpp 跑 Qwen3.5-0.8B 做工具调用）。
> 重点：能不能本地跑、怎么接、输入输出接口长什么样。
>
> **本文严格区分「确认的事实」（有来源链接）与「推测/未查到」。** 所有来源为公开网页（GitHub / HuggingFace / 官方 README），部分为第三方博客（可信度较低，已标注）。

---

## 0. 一句话结论（TL;DR）

- **两类都是「决策模型」**：一段文本（state）+ 一组**结构化问题**（choice/noul/score）进 → **每题一个概率分布/浮点数**出，**单次前向、不生成 token**。这与你现在的「自回归 LLM + 工具调用」是完全不同的范式。
- **两者都能本地跑，而且都有 llama.cpp / ggml 生态的 C++ 运行时**，这点非常关键：
  - **Laya**：`laya.cpp`（MIT，CUDA/Vulkan/CoreML/CPU，自带 JEV 兼容 HTTP `/v1/systemone`）——**最适合你的桌面启动器**。
  - **Kev**：`dohnuts.cpp`（Apache-2.0）原生 C++/llama.cpp 后端支持 kev profile（0.8B/4B），CPU 可跑，自带 `/v1/systemone`。也有第三方 GGUF（`taigrr/kev-0.8b-gguf`、`DreamBlooms/kev-0.8b-GGUF`）。
- **能否像 Qwen3.5-0.8B 那样用「裸 llama-server」跑？——不能直接跑。** 决策输出的是「选项概率」而非 token，需要一个**额外的决策头（decision/pointer head）**读取 hidden state 再做 softmax。裸 `llama-server` 只当**编码器**用（`--embeddings --pooling none` 取 hidden state），**决策头必须在 Python 或专用 C++ runtime 里跑**。这是「决策模型 ≠ GGUF 直接 chat」的核心原因。
- **集成形态建议**：决策模型作为一个**独立本地推理服务进程**（`laya-cli --server` 或 `dohnuts-cli --server`），暴露 `POST /v1/systemone`；你的启动器用 HTTP 调它做**工具路由 / 意图分类**，LLM 仍由 llama.cpp 负责生成。两者并存，互不干扰。

---

## 1. Kev 概览

### 是什么
- Kev 是 **Jev-like 的小型决策模型家族**，由 **Jared Palmer**（jaredpalmer）开源，构建在 **Qwen3.5 / Qwen3.8** 底座之上。架构来自对 TypeSafe **Jev** 的逆向分析（[Archer Hume: Jev's Architecture Unmasked](https://archerhume.com/posts/jevs-architecture-unmasked)）。
- **它就是「决策模型」**：输入一段文本（`state`）+ 一组类型化问题，**一次前向**输出每题的概率分布，**不生成任何文本**。（来源：kev-0.8b 模型卡 "a decision model: one document (the state) and a set of typed questions in, a probability distribution per question out, in one forward pass. No text generation."）
- **与 TypeSafe Jev 的关系**：
  - Jev 是 TypeSafe 的**闭源托管**决策模型，定义了 `/v1/systemone` 这个 wire format 和「System One 模型」品类。
  - Kev 是**开源复刻/替代**，**API 与 Jev 兼容**：官方说法「Drop-in for Jev: the TypeSafe Python SDK works against a Kev server unchanged」。即 TypeSafe 的 Python SDK 换个 `base_url` 就能指向本地 Kev 服务器。
  - Kev **未用任何 Jev 输出做训练**（独立训练）。

### 体量与 License
- **License：Apache-2.0**（adapter + head）；Qwen3.5 底座也是 Apache-2.0。**允许商用/集成**。数据集另有各自 license。
- 形态：每个 checkpoint 是 **rank-16 LoRA adapter（约 11.3M 可训练参数）+ 一个小的 pointer head**，叠加在**冻结的 Qwen base** 上。所以 **加载时需要底座模型**（Qwen3.5-0.8B-Base 等）。Kev-27B 例外（全量微调，51GB）。

### 型号（来源：kev README 表格）
| 型号 | 底座 | 准确率（New Sources, dev/test） | 准确率（Trained Sources） | Brier(越低越好) | 跑在哪 |
|---|---|---|---|---|---|
| **Kev-0.8B** | Qwen3.5-0.8B-Base | 0.648 / 0.697 | 0.827 / 0.838 | 0.481 / 0.416 | 任意 Apple Silicon、L4、笔记本 |
| Kev-4B | Qwen3.5-4B-Base | 0.817 / 0.838 | 0.873 / 0.865 | 0.269 / 0.242 | 32GB Mac、L40S、H100 |
| Kev-9B | Qwen3.5-9B-Base | 0.820 / 0.852 | 0.874 / 0.873 | 0.289 / 0.217 | 32GB Mac、L40S、H100 |
| Kev-27B | Qwen3.8-27B(post) | 0.851 / 0.889 | 0.865 / 0.866 | 0.225 / 0.156 | 80GB GPU |
| *Jev（闭源）* | hosted | 0.857 | 0.845 | 0.211 | TypeSafe API |

- **0.8B 适用场景**：「size matters more than accuracy」——内存紧张时用。**准确率明显低于 4B/9B**，尤其 out-of-domain（0.65~0.70 vs 4B 的 0.82）。
- **官方建议从 4B 起步**，0.8B 是最小成员。
- 0.8B 在 **JevBench public items**（231 条）上 accuracy 0.636（hard tier 0.360）。详见 kev-0.8b 模型卡。
- **重要警告（来自 kev-0.8b 模型卡）**：0.8B 这版在 **When2Call**（判断「要不要调工具/补参数/拒绝」）上**反而变差**（0.26→0.17，低于四选一瞎猜），官方原话 **"Do not use this checkpoint for tool-call routing."**。→ 如果你要用 0.8B 做工具路由，必须**自己微调**，不能直接零样本用。

### 输入输出接口（这是你要的）
- **三种调用方式**：
  1. **HTTP API**（推荐）：`uv run --extra serve python -m kev.serve --run jaredpalmer/kev-0.8b --port 8009`，然后 `POST /v1/systemone`。
  2. **TypeSafe Python SDK**（`typesafe_sdk`）：`TypeSafeClient(api_key="local", base_url="http://127.0.0.1:8009", model="kev-latest")` → `client.system_one(state=..., questions={...})`。
  3. **Python 直接加载**（`DecisionModel.probs()`，repo 内 `kev/model.py`）——面向训练/评测。
- **不是 vllm**；是 `kev.serve` 自带推理服务（torch/CUDA/ROCm/MLX）。

**请求格式（真实示例，来源 kev README）：**
```bash
curl -s localhost:8009/v1/systemone -H 'content-type: application/json' -d '{
  "state": "Shoes arrived two weeks late and in the wrong size...",
  "model": "kev-latest",
  "questions": {
    "department": {"type": "choice", "instructions": "Which team should handle this?",
                   "criteria": {"returns": "...", "shipping": "...", "billing": "..."}},
    "escalate":   {"type": "noul",  "instructions": "Does this need urgent human attention?"},
    "frustration":{"type": "score", "instructions": "How frustrated is the customer?",
                   "criteria": ["Calm", "Frustrated", "Very angry"]}
  }}'
```

**响应格式：**
```json
{
  "answers": {
    "department":  {"type":"choice","choice":"returns","confidence":0.21,
                    "probabilities":{"returns":0.47,"shipping":0.28,"billing":0.25}},
    "escalate":    {"type":"noul","noul":0.93},
    "frustration": {"type":"score","score":1.44,"confidence":0.34,
                    "legend":{"0":"Calm","1":"Frustrated","2":"Very angry"},
                    "probabilities":{"0":0.00,"1":0.56,"2":0.44}}
  },
  "usage":{"input_tokens":101,"output_tokens":161},
  "latency_ms": 495
}
```

### 三类问题（Question types）
- **`noul`（是否/Yes-no）**：返回 `noul` = 「yes」的概率（0~1 浮点）。
- **`choice`（多选）**：1–255 个选项，每项可带描述。返回 `choice`（最可能项）+ `probabilities`（全分布）+ `confidence`。
- **`score`（评分/序数）**：1–255 个有序等级描述。返回 `score`（期望等级索引，从 0 起）+ `legend` + `probabilities` + `confidence`。
- **一次可问任意多个问题**：所有问题**共享同一段 state**，但**互相隔离**（问题看不到彼此）。内部按 token 预算（每次前向最大 16384 token）分批，**内存不随问题数增长**。也有 `/v1/systemone/permute`（测选项顺序敏感度）和 `/v1/systemone/separate`（每题单独前向）。
- **置信度公式**（与 TypeSafe reference adapter 一致）：choice `K>1` 时 `conf=(p_max-1/K)/(1-1/K)`；score 用 `max(0, 1 - E|level-mode|/D)`。**这些不是实测准确率，只是分数。**

### 训练方式（可微调）
- 可在**自有标注数据**上微调。格式：JSONL，每行一个请求 + 每题 `label`（choice=选项名，noul=true/false，score=等级序号）。
- 命令：`uv run python -m kev.train --data train.jsonl --base Qwen/Qwen3.5-4B-Base --init_from jaredpalmer/kev-4b ...`。`--init_from` 从已发布 checkpoint 继续，别从 base 从头训（会丢掉已有能力）。
- **效果**：微调对准确率提升显著（示例：Kev-4B 67.7%→73.6%；真实数据 0.804→0.904）。也有 coding-agent skill（`npx skills add jaredpalmer/kev@kev-finetune`）在 Modal 上一键跑全流程（约 $1/H100）。0.8B 用 `--batch 1 --accum 8` bf16 可在 **4GB GPU** 上训练。

### 本地依赖
- **Python 3.12/3.13 + uv**；`uv sync --extra serve`。后端：**CUDA/ROCm（GPU）/ MLX（Apple Silicon）**。CUDA 上 Qwen3.5 需 `flash-linear-attention`。
- **不是 vllm**；`kev.serve` 自带 HTTP 服务（`/v1/systemone`，类似 llama-server 的本地服务）。
- 依赖栈：**transformers + PyTorch + peft**（transformers>=5.17, peft>=0.21）。
- **但也有纯 C++ 路线**：`dohnuts.cpp` 支持 kev profile（见第 3 节）。

---

## 2. Laya 概览

### 是什么
- Laya 是 **Convai Innovations**（作者 Nandakishor Mukkunnoth）的**开源、多语言、非自回归 System 1 决策引擎**。**Apache-2.0**。
- 与 Jev 同类：`choice`/`score`/`noul` 三类问题，**一次前向**返回概率分布，**不生成文本**。自称比 Jev 快（33ms/问 vs Jev 236–276ms）、多语言（100+）、可自托管、可微调。
- **架构与 Kev 不同（关键区别）**：
  - Laya 基于 **encoder**（**ModernBERT-large 421M / mmBERT-base 322M**），不是 Qwen 解码器。
  - 训练用 **RLCD**（对严格 proper scoring rule 做强化学习）。
  - 有一个 **Router**：按检测到的脚本/语言把请求分派到不同 checkpoint。
  - Kev 基于 **Qwen 解码器 + LoRA + pointer head**（decoder-only，指针式读出）。
- **Laya vs Kev（第三方博客 [orcarouter.ai/blog/laya-vs-kev](https://www.orcarouter.ai/blog/laya-vs-kev)，标题《Laya vs Kev: A Checkpoint Against a Training Recipe》）**：核心观点——Laya 是**一个开源 checkpoint**，Kev 是**一套可复现的训练配方/家族**。（此为第三方观点，可信度中等，仅作参考。）"Laya vs Nimble"、"Laya vs Decider" 是同一站点的对比文，属第三方评测。

### 权重在哪（下载地址）
| Checkpoint | 编码器 | 参数 | 上下文 | 用途 | 链接 |
|---|---|---|---|---|---|
| `laya` (english) | ModernBERT-large | 421M | 512 | 英文 | https://huggingface.co/convaiinnovations/laya |
| `laya-multilingual` | mmBERT-base | 322M | 1024（可到 8192） | 100+ 语言，更快 | https://huggingface.co/convaiinnovations/laya-multilingual |
| `laya-typed-decisions` | ModernBERT-large | 421M | 1024 | typed-decisions 工作流（微调版） | https://huggingface.co/convaiinnovations/laya-typed-decisions |

- **License：Apache-2.0**（Convai Innovations）。
- 体量：322M–421M，**比 Kev-0.8B 更小、更快、CPU 更友好**。
- 浏览器微调变体（另一个项目用）：`cklxx/laya-browser`、`ichenney/laya-browser-v32b`。
- **也有 GGUF**：`fr0stbit3/laya-gguf`、`ZeroDegress/laya-gguf`、`Weidows/laya-multilingual-GGUF`。

### 怎么本地跑（接口与推理引擎）
- **Python SDK（最简单）**：`pip install laya`（PyPI 包 `laya`）。`from laya import Router; router.predict(state, questions)`。支持 CPU / CUDA / Apple MPS / Intel XPU / **ONNX**（`laya[onnx]`，含 INT8 CPU 量化）/ **MLX**（Apple）。
- **HTTP 服务**：`pip install "laya[serve]"` → `laya-serve`（或 `python examples/server.py`），暴露 `/predict`、`/predict/batch`、**`/v1/systemone`（JEV 兼容）**。
- **`laya-browser-agent`（ChenneyZhuang）怎么加载 Laya**：它是 `localdecide` 这个 harness，通过 `LayaMLXBackend`（Apple）或 `LayaTorchBackend`（其它）**在 Python 进程内 import Laya 并加载 checkpoint**，或用 `HTTPBackend` 指向任意 `/v1/systemone` 端点。它自称「本地、无云、无 API key」——因为权重本地、推理本地。它也提供 `localdecide serve --port 8791` 起 `/v1/systemone` 服务、MCP server、CLI。
- **C++ 原生运行时**：`laya.cpp`（MIT，见第 3 节）。

### 输入输出接口（与 Kev 同构）
- **完全相同的三类问题**：`choice` / `score` / `noul`，`criteria` 字段格式与 Kev/Jev 一致（choice=选项→描述 map，score=等级数组，noul=true/false 描述）。
- 返回 `answers.<id>.{choice|score|noul}` + `probabilities` + `confidence`（+ `routing` 元数据）。
- **一次可问多个问题，单次前向**；支持 `predict_batch`/`decide_batch` 批量。
- **设计问题的方式**：给 state（文本/邮件/工单/JSON），然后每题写 `instructions`（自然语言问题）+ `criteria`（选项及各自语义描述）。示例见 Laya README quickstart（department/urgency/churn_risk）。
- **Laya 已知坑（README「Honest limits」，务必注意）**：
  - **零样本在你的域上可能很弱**：base checkpoint 在 typed-decisions 上接近随机（0.36），**0.766 那个高分是「微调后」的**。官方定位：「Laya 是一个可快速特化的 base，不是零样本决策引擎」。
  - **noul 会跟着选项标签走而非 state**（英文 checkpoint 最严重）——建议给 noul 加 `criteria`，或用 `labels` 覆盖，或用两选项的 choice 替代。
  - **选项数 >20 时准确率骤降**（token 预算问题）：Banking77 上 Laya 0.425 vs Jev 0.870。工具/意图多时要用 `predict_shortlist`（embedding 先筛 top-k）或拆成粗/细两问。
  - **choice 标签避免用 true/false/yes/no**（会被标签本身带偏）。
  - 置信度出厂**过度自信**，需按域拟合温度（ECE 0.466→0.081）。

---

## 3. Kev vs Laya 对比

| 维度 | **Kev** | **Laya** |
|---|---|---|
| 底座架构 | Qwen3.5/3.8 **decoder-only** + LoRA r16 + **bilinear pointer head** | **encoder**（ModernBERT-large / mmBERT-base）+ decision head |
| 最小可用体量 | 0.8B（+需 Qwen3.5-0.8B-Base） | **322M–421M**（更小更快） |
| License | Apache-2.0 | Apache-2.0 |
| 零样本准确率（own-domain 未微调） | 中等；out-of-domain 0.8B 弱 | **接近随机**（base）→ 微调后 0.766 |
| 多语言 | 主要英文 | **100+ 语言，强项** |
| 置信度校准 | 内置温度，出厂校准较好 | 出厂过度自信，需自拟合温度 |
| 工具路由（When2Call） | **0.8B 明确「不要用于 tool-call routing」**（需微调） | 未针对该基准；但可微调（如 browser 场景） |
| Python 依赖 | transformers+torch+peft（较重） | `pip install laya`（torch 或 onnx，较轻） |
| **本地 C++/llama.cpp 跑** | ✅ `dohnuts.cpp`（kev profile，0.8B/4B） | ✅ `laya.cpp`（MIT，CUDA/Vulkan/CoreML/CPU） |
| 专为浏览器/agent 场景 | 否（通用决策） | 是（laya-browser-agent / jev-ultrafast 生态丰富） |
| 微调成本 | Modal ~$1/H100；0.8B 可 4GB GPU | Kaggle 免费 2xT4 ~4-5h |

**哪个更适合本地集成？**
- 若**启动器是中文/多语言**、追求**小体积 + CPU 快 + 现成 C++/HTTP 服务**：**Laya 更合适**（322M、`laya.cpp`、多语言、`laya-serve`/`/v1/systemone`）。
- 若**只做英文**、要**更强的零样本准确率和校准**、且能接受 Qwen3.5 底座 + 微调：**Kev-4B**（0.8B 太弱且不适合工具路由）。
- 两者都是「base 需微调才准」，这是**决策模型的共同现实**。

---

## 4. 本地集成可行性（重点）

### 能不能用 llama.cpp / llama-server 直接跑？
**不能「直接」跑，但能「借助」。** 原因与路径（**已确认**）：

1. **决策输出的是「选项概率分布」，不是 token。** 需要一个**决策头**读取特定 hidden state（Kev：`<decide>` 与各 `</opt>` 的双线性打分；Laya：encoder hidden + head），再 softmax + 温度缩放。裸 `llama-server` 的生成/chat 路径用不上。

2. **Laya → llama.cpp（两条路，均已确认存在）**：
   - **`laya.cpp`（MIT，lkarlslund）**：**原生 C++ 推理**，支持 **CUDA / Vulkan / Apple Core ML / CPU**，**无需 Python**，自带 **JEV 兼容 HTTP server `POST /v1/systemone`** + 自动 batching。有 Windows/Linux/macOS 预编译二进制。**这是最适合你桌面启动器的路径**（单二进制、离线、跨平台）。→ https://github.com/lkarlslund/laya.cpp
   - **裸 llama-server 当编码器 + Python 跑 head**：`fr0stbit3/laya-gguf` 用 `llama-server -m laya-F16.gguf --embeddings --pooling none` 取 hidden state，再用 Python 里的 `laya` 包跑决策头。**注意**：GGUF 只含 ModernBERT backbone，决策头在旁路 `laya-head.safetensors`，必须在 llama.cpp 之外跑；且 `laya` 包仍需下载一次原始权重（取 head 结构 + tokenizer）。
   - **上游 llama.cpp PR #29363「laya: Add support for the laya multilingual decision model」**（Clauszy）：拟原生支持 laya。**⚠️ 合并状态未查到确认**（网页被截断），不要假设已进主线。

3. **Kev → llama.cpp（已确认）**：
   - **`dohnuts.cpp`（Apache-2.0）**：原生 C++/llama.cpp（pinned v0.4.1）后端，**有 `kev` profile**，支持 kev-0.8b/4b（**bilinear pointer head**）。CPU 默认可跑（prefill ~21 tok/s @8 线程，一次两问需几秒），可选 CUDA/Vulkan/ROCm/Metal。自带 **`/v1/systemone` HTTP server**。→ https://github.com/DreamBlooms/dohnuts.cpp
   - 预转换 GGUF：`DreamBlooms/kev-0.8b-GGUF`、`DreamBlooms/kev-4b-GGUF`、`taigrr/kev-0.8b-gguf`（Go 端 `gojev`）。**注意**：Kev 的 LoRA 需先 merge 进 base，pointer head 单独存成 `kev-head.f32`（不是标准 GGUF）。
   - ⚠️ **Qwen3.5 是 hybrid（gated-delta-net + attention）**，delta-net 是 CPU 瓶颈，**CPU 上较慢**；Kev-0.8B 在 Mac 上因 DeltaNet 无 MPS 实现也偏慢。

### 若不用裸 llama.cpp，本地集成要什么 + 依赖/体积成本（Python + PySide6 桌面启动器）
**推荐架构**：决策模型作为**独立本地服务子进程**，启动器用 `requests`/`httpx` 调 `POST /v1/systemone`。LLM（工具调用/生成）仍走现有 llama.cpp。

- **方案 A（首选，最轻）：`laya-cli --server` / `laya.cpp` 二进制**
  - 依赖：**一个独立可执行文件**（laya.cpp 有预编译 Windows x64 CUDA/Vulkan 二进制）。**不污染你的 Python 依赖**。
  - 体积：模型 ~400M–1GB（GGUF F16 933M / Q8_0 563M / Q4_K_M 414M；或原始 322–421M）。
  - 进程内无 torch，**无 PySide6 冲突风险**。

- **方案 B：Python `laya` 包（ONNX 后端）**
  - `pip install "laya[onnx]"`，可用 **INT8 CPU 量化**。相比 torch 轻，但仍是一坨 Python 依赖（torch 或 onnxruntime）。
  - ⚠️ **PySide6 桌面打包（PyInstaller）风险**：引入 torch/onnxruntime 会让打包体积 +1~2GB 且易踩 Qt/线程/事件循环冲突（laya README 明确警告：模型 runtime 会创建 event loop，勿与 Playwright Sync 混在同一进程；同理需注意与 Qt 主线程隔离）。**建议决策模型跑在子进程/独立服务里，主线程只发 HTTP。**

- **方案 C：Kev（transformers/PyTorch）**
  - 依赖最重：**transformers>=5.17 + torch + peft + flash-linear-attention（CUDA）**。
  - 体积：Qwen3.5-0.8B-Base + adapter + head。CPU 较慢。
  - 除非要 Kev 的校准/准确率优势，否则对桌面启动器偏重。

**依赖/体积小结（针对 PySide6 离线启动器）**：
| 方案 | 引入依赖 | 打包体积增量 | Qt/线程风险 | 推荐度 |
|---|---|---|---|---|
| laya.cpp / dohnuts.cpp 二进制 + HTTP | 无 Python 依赖 | ~0.5–1GB 模型 | 低（子进程） | ⭐⭐⭐⭐⭐ |
| Python `laya[onnx]` | onnxruntime | ~0.5–2GB | 中 | ⭐⭐⭐ |
| Python `laya`(torch) / kev(transformers) | torch+transformers(+peft) | ~2–5GB | 高 | ⭐⭐ |

### 怎么接进现有 llama.cpp 本地栈
```
[用户输入] → 启动器(PySide6)
   ├─(A) 意图/工具路由：HTTP POST → laya-cli/dohnuts-cli --server (/v1/systemone)
   │        → {tool: choice(probabilities), 需否确认: noul, 紧急度: score}
   │        → 高置信度直接执行工具；低置信度回退到 LLM 或问用户
   └─(B) 复杂生成/工具调用：现有 llama.cpp (llama-server) → Qwen3.5-0.8B
```
- 决策模型与 llama.cpp **并列**，不替换。决策模型做「快、便宜、带置信度」的分类/路由；LLM 做「生成、多步工具调用」。
- 决策模型服务可做成 PySide6 启动时拉起的**子进程**，或常驻本地服务（127.0.0.1）。

---

## 5. 在「工具选择/意图分类」场景的落地方式

### 用决策模型替代现在的「关键词工具挂载」
现状（推测）：你可能用关键词/正则把用户输入映射到工具。决策模型可以把这一步升级为**概率化、可置信度门控的路由**。

**问题设计（choice 做工具选择）：**
```jsonc
{
  "state": "<用户当前请求/对话上下文/可用工具描述拼成的文本>",
  "questions": {
    "tool": {
      "type": "choice",
      "instructions": "Which tool should handle this Minecraft launcher request?",
      "criteria": {
        "launch_game":   "start or launch the game, play, enter world",
        "install_mod":   "download/install/manage mods or modpacks",
        "manage_server": "join/create/configure a multiplayer server",
        "settings":      "change launcher or game settings, memory, java path",
        "account":       "login, Microsoft account, skin, profile",
        "none":          "none of these tools fit"
      }
    },
    "needs_confirm": {"type":"noul","instructions":"Is this action destructive or irreversible (delete world, uninstall, spend)?"},
    "urgency":       {"type":"score","instructions":"How urgent?","criteria":["can wait","soon","now"]}
  }
}
```

**关键实践（结合两份 README 的最佳实践）：**
1. **选项数控制在 ≤20**，否则准确率骤降（Laya 明确）。工具多时用 `predict_shortlist`（embedding 先筛 top-k）或拆「粗类→细类」两问。
2. **每个工具写清语义描述（criteria 的 value）**，这比 instructions 更影响准确率。
3. **choice 标签用语义词或 A/B/C，避免 true/false/yes/no**（Laya 会被标签带偏）。
4. **必须给 `none` 选项**，让模型能「不匹配」。
5. **置信度门控**：`probabilities` 最大值高（如 ≥0.8）→ 直接路由；低 → 回退 LLM 或问用户。Kev 甚至可用内置校准温度的 `confidence` 设阈值（但官方提醒先在自有数据上测阈值）。
6. **用 `noul` 做安全确认**（是否需要人工确认/是否危险），替代纯关键词 `RISKY_HINTS`。
7. **微调**：零样本在自己域上往往不准（Laya base 近随机；Kev-0.8B 工具路由明确不行）。**准备几百~几千条标注**（工具名当 choice label）微调，准确率才有意义。Kev-4B/9B 或 Laya-typed-decisions 都支持。

**「替代关键词」的现实预期**：
- 短期：**决策模型 + 关键词并存**（关键词做确定性强的快速路径，决策模型做模糊/兜底）。
- 中期：标注数据后微调，决策模型主导路由，关键词降级为 sanity check。

---

## 6. 风险与未知（明确标注）

**已确认为坑 / 风险：**
- **Kev-0.8B 模型卡明确「Do not use this checkpoint for tool-call routing」**（When2Call 上反而退化）。→ 工具路由场景必须微调，或上 4B/9B。
- **Laya base 零样本接近随机**，高分靠微调；**noul/choice 标签偏置**、**>20 选项骤降**、**score 序数最弱**、**出厂过度自信需校准**。
- **裸 llama.cpp 无法直接输出决策**，必须加决策头；GGUF 只是 backbone。
- **CPU 上 Qwen3.5 hybrid（delta-net）慢**（Kev）；Laya encoder 在 CPU/ONNX 上更快。
- **PySide6 打包**：torch/onnxruntime 依赖重、易与 Qt 事件循环/线程冲突 → 建议子进程/HTTP 隔离。
- 选项顺序会影响答案（Kev 也有 option-order flip ~0.08）；问题间隔离不解决选项间影响。

**未查到 / 需自行验证（不要当事实）：**
- **llama.cpp 上游 PR #29363（laya support）是否已合并进主线**——网页截断，**未确认**。目前请依赖 `laya.cpp`/`dohnuts.cpp` 或 HF GGUF。
- **Laya 的「统一」官方 benchmark vs Jev**：Laya README 里的对比数字部分来自第三方发布（"never measured here"），**可信度中等**，需自测。
- **JevBench**：Kev 提到 JevBench（0.8B 全部 231 条 0.636，hard 0.360），但**JevBench 官方榜单/完整定义未直接查到**。
- **Laya 在「Minecraft 工具路由」这个具体域的准确率**——无现成数据，必须自测/微调。
- **orcarouter.ai 的「Laya vs Kev」等对比文为第三方博客**，立场/方法未知，仅作参考，不作架构依据。
- 未逐一核实所有 GGUF 转换的数值精度（laya-gguf 自称「lightly tested」，Q4_K_M 概率可偏移 0.02–0.03）。

---

## 7. 关键链接

### Kev
- GitHub（README/训练/部署/API）：https://github.com/jaredpalmer/kev
- Kev-0.8B 模型卡：https://huggingface.co/jaredpalmer/kev-0.8b
- Kev 家族权重集合：https://huggingface.co/collections/jaredpalmer/kev-6aad9d0ea49f2589665e07cd
- Kev-4B：https://huggingface.co/jaredpalmer/kev-4b （9B：/kev-9b；27B：/kev-27b）
- Kev-0.8B GGUF（Go/gojev）：https://huggingface.co/taigrr/kev-0.8b-gguf
- Jev 架构逆向（Kev 灵感来源）：https://archerhume.com/posts/jevs-architecture-unmasked
- TypeSafe System One API：https://docs.typesafe.ai/api

### Laya
- 官方仓库（README/训练/微调/HTTP/MCP）：https://github.com/NandhaKishorM/laya
- Laya 权重：https://huggingface.co/convaiinnovations/laya
- Laya-multilingual：https://huggingface.co/convaiinnovations/laya-multilingual
- Laya-typed-decisions：https://huggingface.co/convaiinnovations/laya-typed-decisions
- Laya GGUF：https://huggingface.co/fr0stbit3/laya-gguf （另有 ZeroDegress、Weidows/laya-multilingual-GGUF）
- laya-browser-agent（localdecide）：https://github.com/ChenneyZhuang/laya-browser-agent
- Laya 文档：https://nandhakishorm.github.io/laya/

### 本地 C++/llama.cpp 运行时（集成重点）
- **laya.cpp**（MIT，CUDA/Vulkan/CoreML/CPU，自带 /v1/systemone）：https://github.com/lkarlslund/laya.cpp
- **dohnuts.cpp**（Apache-2.0，llama.cpp 后端，含 kev/decider/thisthat/tev1 profile，自带 /v1/systemone）：https://github.com/DreamBlooms/dohnuts.cpp
- Kev GGUF（dohnuts 系）：https://huggingface.co/DreamBlooms/kev-0.8b-GGUF （4b：/kev-4b-GGUF）
- llama.cpp laya 支持 PR（**合并状态未确认**）：https://github.com/ggml-org/llama.cpp/pull/29363

### 对比/评测（第三方，仅参考）
- Laya vs Kev：https://www.orcarouter.ai/blog/laya-vs-kev
- Laya vs Nimble：https://www.orcarouter.ai/blog/laya-vs-nimble
- Laya 解读：https://www.orcarouter.ai/blog/laya-decision-model-explained
- TypeSafe Jev 评测（Arize）：https://arize.com/blog/typesafe-jev-llm-judge/

---

*调研时间：基于公开网页抓取。所有「已确认」均可由上列链接核对；「未查到」部分请勿臆测。*
