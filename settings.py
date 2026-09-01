# -*- coding: utf-8 -*-
"""
启动器设置:用户名、内存、版本隔离等,持久化到 config.json。

学到的模式:配置文件的读写。
- 读取:文件里的值覆盖默认值,缺的字段补默认(这样以后加新设置,旧配置也不会坏)
- 保存:写成 JSON,人类可读可改
"""
import json
import os

from paths import CONFIG_PATH  # 与 paths.BASE_DIR 一致(打包后 = exe 旁边,便携)

DEFAULTS = {
    "username": "Steve",        # 离线模式游戏名
    "memory_gb": 4,              # 给游戏分配的内存(默认 4G,整合包/Mod 多才够;设置里可改)
    "version_isolation": True,   # 版本隔离:每版本独立游戏目录
    "game_dir": "",              # 游戏目录(.minecraft 位置;空 = 启动器目录下默认位置)
    "skills": {},                # 技能启停状态 {技能id: true/false}(见 skill_manager.py)
    "language": "auto",          # 界面语言:auto(跟随系统)/ zh / en / 语言包id(如玩梗版;见 i18n.py)
    "sync_minecraft_language": True,  # 启动前用启动器/系统语言同步实例 options.txt 的 lang 项
    "ui_mode": "beginner",       # 界面模式:beginner=全面(多提示/科普)/ expert=摘要(精简)。
                                 # 对外显示名叫「全面 / 摘要」(不用"新手/专家",免得显得看不起新手);
                                 # 值保持 beginner/expert 以兼容旧配置。
    "microsoft_login": True,     # 正版登录开关(默认 True,正式版将要求正版登录)。
                                 # 无 GUI 设置项;想跳过正版登录可手动改 config.json 的 microsoft_login=false;
                                 # 也可以让 AI 关掉(告诉它"关掉正版登录")。
    "login_method": "offline",   # 登录方式:offline(离线昵称) / microsoft(微软正版)。
                                 # 正版登录后这里变成 microsoft,启动游戏用正版凭证。
    "ms_credentials": {},        # 微软正版凭证(登录成功后存 refresh_token/username/uuid/access_token 摘要)。
                                 # 敏感,只存本机;不随包分享。
    "ms_client_id": "",          # 微软 OAuth client_id(可选覆盖;留空=用官方白名单 id 00000000441cc96b)。
                                 # 微软已收回 Mojang 公开 id,自注册应用后填这里即可正版登录;敏感,只存本机。
    "tutorial_auto": True,       # 新手教程自动播放:首次启动引导里选「新手」时自动进教程;选「老手」不进。
                                 # 之后任何时刻都能在 设置→界面→重播引导教程 重播。
                                 # 这里主要记住"是否已首次决定过",避免每次都弹。
    # AI 助手(OpenAI 兼容接口)
    "ai_provider": "deepseek",
    "ai_base_url": "https://api.deepseek.com/v1",
    "ai_api_key": "",
    "ai_model": "deepseek-chat",
    # 默认仅允许启动器数据(AMCL)和游戏目录(.minecraft)内的正常操作；每项 AI 动作仍会先展示预览确认。
    "ai_permission": "launcher_write",    # AI 文件权限:readonly / launcher_write / workspace_write
    "context_window": 65536,       # AI 上下文窗口上限(tokens),DeepSeek-chat 为 64K
    "ai_multimodal": False,        # 模型是否支持图片输入(多模态):True = AI 对话框显示图片相关按钮;
                                   # 目前准备使用的本地模型不支持,未来换多模态模型时把这里改成 True 即可
    # 内置本地模型(provider 选 local_builtin 时生效):首次用会后台下载(约500MB,镜像优先)
    "ai_local_model": "qwen3.5-0.8b-xlam-q4km",   # 本地模型 id(与 model_registry.RESOURCES 对应)
    "ai_local_auto_download": True,               # 首次用到且未下载 → 自动后台下载(False = 不下载直接走云端)
    "ai_in_game": "off",                          # 游戏内 AI 通道:off(关闭,卸载模型省内存)/ cloud(云端)/ local(本地)
    "ai_in_game_quota": 50,                       # 游戏内 /ai 每日总额度(次数;0=不限)——保护服主 API
    "ai_in_game_cool": 5,                         # 游戏内 /ai 每玩家冷却(秒)——防单玩家刷
    "ai_in_game_quota_exempt": "",                # 豁免每日额度的特例玩家(逗号分隔,如 "Steve,Alex")
    "ai_in_game_admin": "",                       # 可豁免的"服主/管理员"名单(逗号分隔)
    "ai_strategy": "local_first",                 # AI 策略三档:local_first(本地优先,省)/ cloud_first(云端优先,强)/ hybrid(混合平衡)
    "ai_mod_translate": True,                     # Mod 描述本地 AI 翻译(英→中):True=详情显示中文+机翻标注 / False=原文
    "ai_mod_translate_source": "local",          # Mod 描述翻译来源:local(默认) / cloud(使用已配置云端模型)
    "ai_cloud_tool_log": True,                     # 云端工具调用训练日志:仅本机 JSONL，可在设置关闭
    # ---- 云端 / 本地 两组独立设置(设置 UI 分开,ai_source 决定当前用哪边)----
    "ai_source": "cloud",          # 当前模型来源:cloud(云端)/ local(本地)
    # 云端模型(ai_source=cloud 时生效;DeepSeek/OpenRouter/硅基流动/智谱/通义/自定义)
    "ai_cloud_provider": "deepseek",
    "ai_cloud_base_url": "https://api.deepseek.com/v1",
    "ai_cloud_api_key": "",
    "ai_cloud_model": "deepseek-chat",
    # 本地模型(ai_source=local 时生效):builtin(内置)/ ollama / lmstudio
    "ai_local_mode": "builtin",
    "ai_local_endpoint": "",       # ollama/lmstudio 的服务地址(内置模型留空)
    # 下载镜像策略(见 downloader.MIRROR_STRATEGIES):
    #   smart_official 官方优先(官方慢/失败时换镜像) / mirror_first 镜像优先(失败回官方)
    #   official_only 只用官方 / mirror_only 只用镜像
    "mirror_strategy": "smart_official",
    # 用到的镜像站:bmclapi / custom:<id>(自定义,见 downloader.MIRROR_SOURCES)。
    # 是否用官方由 mirror_strategy 决定,这里不再出现 "official"
    "mirror_source": "bmclapi",
    "custom_mirrors": [],          # 自定义镜像源列表:[{"id","name","url"}]
    "plugin_registries": [
        # 默认填官方插件仓库(erfanyo/Agent_Minecraft_Launcher);用户可手动添加其它仓库
        {"url": "https://github.com/erfanyo/Agent_Minecraft_Launcher", "name": "erfanyo/Agent_Minecraft_Launcher"},
    ],       # 插件仓库源:[{"url","name"}] 手动添加(你的官方仓库默认在此)
    # ---- 自定义背景(阶段 2;默认关,决策 3)----
    "ui_wallpaper_source": "none",     # 壁纸源:none(关闭)/ preset(预设渐变)/ official(官方,首启下载)/ user(本地图片)
    "ui_wallpaper_preset": "teal",     # 预设壁纸 id(见 ui_background.PRESETS)
    "ui_wallpaper_user_path": "",      # 用户图片相对路径(相对 AMCL/cache/,复制进来的)
    "ui_wallpaper_official_id": "",    # 官方壁纸 id(素材待项目方提供)
    "ui_wallpaper_mask": 60,           # 遮罩强度 0~80(%);默认 60(深色遮罩/浅色遮罩自动换色)
    "ui_animations_enabled": True,     # 界面动画开关(淡入/标签切换等);关闭后动画立即到位
}


def suggested_memory_gb() -> int:
    """按机器实际物理内存,返回一个合理的默认给游戏的内存(GB)。

    原则:给够、又不给到反伤(太低整合包开不了,太高在 8G 机器上反而卡)。
    - 物理内存 ≤ 8G  → 4G(保守,整合包勉强够,原版/少量 Mod 流畅)
    - 物理内存 16G   → 6G(整合包 + 光影可跑)
    - 物理内存 ≥ 32G → 8G(放开,可再手动调)
    读不到内存就回退 4G(默认值)。"""
    try:
        if os.name != "nt":
            return 4   # 非 Windows:读物理内存走 psutil 等,这里给保守默认
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_gb = stat.ullTotalPhys / (1024 ** 3)
            if total_gb >= 32:
                return 8
            if total_gb >= 16:
                return 6
            return 4
    except Exception:
        pass
    return 4


def load_settings() -> dict:
    """读配置;没有文件或文件坏了就返回默认值。
    旧版配置(缺 ai_source/ai_strategy 等新字段)自动迁移到新版,并写回磁盘一次。"""
    data = dict(DEFAULTS)
    migrated = False
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                data.update(saved)
                # 旧版镜像配置迁移到"策略"模式:旧版 mirror_source 选"官方源"的,
                # 等价于新策略"官方优先 + 镜像站 BMCLAPI";选镜像的等价"镜像优先"。
                if "mirror_strategy" not in saved:
                    old = saved.get("mirror_source")
                    if old == "official":
                        data["mirror_source"] = "bmclapi"
                        data["mirror_strategy"] = "smart_official"
                    elif old == "bmclapi" or (isinstance(old, str) and old.startswith("custom:")):
                        data["mirror_strategy"] = "mirror_first"
                    # 没有 mirror_source(全新安装)→ 保持默认 smart_official + bmclapi
                # AI 设置迁移:把旧式"单一 provider"配置拆成 云端/本地 两组(拆分设置前,ai_source 不存在;
                # 半升级配置缺 ai_strategy 也在此修正),保证策略与来源连贯,避免旧用户升级后撞云端 401
                if "ai_source" not in saved or "ai_strategy" not in saved:
                    if _migrate_ai(data, saved):
                        migrated = True
        except Exception:
            pass  # 配置文件损坏:退回默认
    if migrated:
        # 把升级后的配置写回,旧文件一次到位(下次启动不再重复迁移)
        try:
            save_settings(data)
        except Exception:
            pass
    return data


def _migrate_ai(data: dict, saved: dict):
    """把旧式"单一 ai_provider"配置拆成 / 映射到 云端与本地两组设置,并修正 ai_strategy。

    只在老配置(缺 ai_source 或 ai_strategy)时调用,幂等:
    - 用旧配置显式选过的 ai_provider 判断属于云端还是本地,把 ai_base_url/ai_api_key/ai_model 填到对应那一组;
    - 按当前来源推导一套**连贯**的 ai_strategy(本地→local_first / 云端→cloud_first),
      避免旧用户升级后出现『策略显示本地、实际却按云端发请求』的错位(否则可能撞云端 401);
    - 从未配过 AI(旧配置既无 ai_provider 也无 ai_source)→ 保持产品默认,不改策略。"""
    prov = (saved.get("ai_provider") or "").strip()
    old_source = (saved.get("ai_source") or "").strip()
    if not (prov or old_source):
        return False   # 全新/未配过 AI:保默认(不改策略、不拆分)

    # 1) 拆分云端/本地(仅旧配置缺 ai_source 时)
    if "ai_source" not in saved:
        if prov in ("local_builtin", "ollama", "lmstudio"):
            # 本地一侧
            data["ai_source"] = "local"
            data["ai_local_mode"] = "builtin" if prov == "local_builtin" else prov
            data["ai_local_endpoint"] = (data.get("ai_base_url") or "").strip()
            if prov == "local_builtin":
                data["ai_local_model"] = data.get("ai_local_model",
                                                  "qwen3.5-0.8b-xlam-q4km")
            else:
                data["ai_local_model"] = (data.get("ai_model") or "").strip()
        elif prov:
            # 云端一侧
            data["ai_source"] = "cloud"
            data["ai_cloud_provider"] = prov
            data["ai_cloud_base_url"] = (data.get("ai_base_url") or "").strip()
            data["ai_cloud_api_key"] = (data.get("ai_api_key") or "").strip()
            data["ai_cloud_model"] = (data.get("ai_model") or "").strip()

    # 2) 修正/推导 ai_strategy(旧配置缺 ai_strategy 时,按当前来源定,保证连贯)
    if "ai_strategy" not in saved:
        src = data.get("ai_source", "cloud")
        data["ai_strategy"] = "local_first" if src == "local" else "cloud_first"

    return True


def save_settings(settings: dict) -> None:
    """把设置写回 config.json"""
    data = dict(DEFAULTS)
    data.update(settings)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
