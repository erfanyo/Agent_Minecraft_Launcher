# -*- coding: utf-8 -*-
"""
轻量国际化:根据系统语言自动选择界面语言(可在设置里覆盖)。
- language 设置:auto(跟随系统)/ zh / en / 自定义语言包 id(如 aigangjing)
- t(zh, en):按当前语言返回文字;英文没提供时回退中文
- 语言包覆盖层:当前生效的「语言包」若命中某个文本,则用它替换所有文本(第三方/玩梗语言)。
  匹配靠"文本本身":语言包 = {"打开网站": "点它!"},t(中文, 英文) 先查语言包,
  命中用语言包文本,未命中回退 zh/en。这样不用重写任何 t() 调用点即可整包换肤。
- 切换语言后重启启动器生效(界面文字是启动时固定的)。
"""
import json
import os
import locale

_current = "zh"

# ---- 语言包覆盖层 ----
# 当前生效的语言包 id 与内容。pack = {"文本": "替换文本", ...}(按中文原文作 key,也可按英文原文)
_lang_pack_id = ""        # 当前激活的语言包 id(空=未启用语言包)
_lang_pack = {}           # 当前语言包内容 {"中文原文" -> "替换文本"}
# 所有已注册的语言包(runtime 注册来自插件): {pack_id: {"name":..,"pack":{..},"lang"?:..}}
_PACKS = {}
# 语言包加载目录(从启动器私有数据 AMCL/languages/ 加载第三方 .json)
PACK_DIR = ""   # 在 load_packs_from_dir 前为 None;main 启动时 fill


def detect_system_language() -> str:
    """检测系统语言:中文系统 → zh,其他 → en"""
    try:
        code = (locale.getdefaultlocale()[0] or "").lower()
    except Exception:
        code = ""
    return "zh" if code.startswith("zh") else "en"


def set_language(lang: str):
    """lang: auto(跟随系统)/ zh / en / 语言包 id(如 '玩梗版' 的 pack id)。
    若 lang 是一个已注册语言包 id,则同时激活它;否则激活内置 zh/en。"""
    global _current, _lang_pack_id, _lang_pack
    if lang == "auto":
        lang = detect_system_language()
    if lang in _PACKS:
        # 激活语言包:基础语言用该包的 lang 字段,或跟随系统
        p_lang = _PACKS[lang].get("lang") or detect_system_language()
        _current = p_lang or "zh"
        _lang_pack_id = lang
        _lang_pack = _PACKS[lang].get("pack", {}) or {}
    else:
        _current = lang or "zh"
        _lang_pack_id = ""
        _lang_pack = {}


def get_language() -> str:
    """当前语言。若激活了语言包,返回其 pack_id(让 AI 等知道在用什么)。"""
    return _lang_pack_id or _current


def get_base_language() -> str:
    """语言包之下的基础语言(zh/en),供 AI/翻译判断。"""
    return _current


def register_pack(pack_id: str, name: str, pack: dict, lang: str = "") -> None:
    """注册一个语言包(来自插件或目录)。pack = {"原文": "替换文本"}。
    lang: 该包作用于哪种基础语言;'' 表示覆盖所有。"""
    _PACKS[pack_id] = {"name": name, "pack": dict(pack or {}), "lang": lang}


def list_packs() -> dict:
    """所有已注册语言包 {id: {name, lang, count}}。"""
    return {pid: {"name": p.get("name", pid), "lang": p.get("lang", ""),
                  "count": len(p.get("pack", {}))}
            for pid, p in _PACKS.items()}


def get_pack(id_) -> dict:
    return _PACKS.get(id_, {})


# ---- 从目录加载第三方语言包(json)----
def load_packs_from_dir(directory: str) -> int:
    """从 directory 加载所有 *.json 语言包(每个文件 = 一个包)。
    文件格式: {"pack_id": "meme", "name": "玩梗版", "lang": "", "pack": {"打开网站": "点它!"}}
    或直接 {"pack_id": "meme", "name": "玩梗版", "pack": {...}}。返回加载数量。"""
    global PACK_DIR
    PACK_DIR = directory
    n = 0
    if not directory or not os.path.isdir(directory):
        return n
    for f in sorted(os.listdir(directory)):
        if not f.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(directory, f), encoding="utf-8"))
            pid = data.get("pack_id") or os.path.splitext(f)[0]
            register_pack(pid, data.get("name", pid), data.get("pack", {}),
                          data.get("lang", ""))
            n += 1
        except Exception:
            continue
    return n


def t(zh: str, en: str = "") -> str:
    """取当前语言的文字;英文未提供时回退中文。
    若激活了语言包,先查语言包有没有覆盖(用 zh 或 en 原文作 key)。

    三种调用形态(向下兼容):
      t("中文", "英文")      旧式两参
      t(("中文", "英文"))    元组直传(zh=en 元组)
      t("STRING_ID")        新式单项:若该字符串是 strings_table.STRINGS 的 key,
                            则取对应 (中文, 英文) 再返回;否则当作中文原文返回。
    """
    # 懒加载集中的文案表(避免 i18n <-> strings_table 循环导入;表大时只在首用时加载)
    from strings_table import STRINGS
    if isinstance(zh, tuple):
        zh, en = (zh[0], zh[1] if len(zh) > 1 else "")
    elif isinstance(zh, str) and zh in STRINGS:
        zh, en = STRINGS[zh]
    if _lang_pack:
        # 语言包覆盖优先(用中文原文或英文原文作 key)
        if zh in _lang_pack:
            return _lang_pack[zh]
        if en and en in _lang_pack:
            return _lang_pack[en]
    if _current == "en" and en:
        return en
    return zh
