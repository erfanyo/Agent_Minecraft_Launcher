"""Shared assistant model and strategy defaults."""

LOCAL_PROVIDER = "local_builtin"

LOCAL_MODEL_ID = "qwen3.5-0.8b-xlam-q4km"

STRATEGY_LABELS = {
    "local_first": "本地优先(省钱)",
    "cloud_first": "云端优先(更强)",
    "hybrid": "混合(平衡)",
}

STRATEGY_CYCLE = ["local_first", "cloud_first", "hybrid"]


_CLOUD_PROVIDERS = [
    ("硅基流动", "siliconflow"),
    ("DeepSeek", "deepseek"),
    ("OpenRouter", "openrouter"),
    ("Gemini API", "gemini"),
    ("GroqCloud", "groq"),
    ("Cerebras", "cerebras"),
    ("智谱 BigModel", "zhipu"),
    ("通义千问", "dashscope"),
    ("小米 MiMo API", "mimo"),
    ("Ollama", "ollama"),
    ("LM Studio", "lmstudio"),
    ("自定义", "custom"),
]

_LOCAL_MODES = [
    ("内置本地模型", "builtin"),
]
