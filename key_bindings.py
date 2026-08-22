# -*- coding: utf-8 -*-
"""
按键绑定查询(bridge-mod 导出 .bridge/keybindings.json):
- 键码 → 该键绑定的所有操作(天然支持一键多操作,按键重合正常)
- 操作名 → 对应按键(反向查询,含 mod 按键)
- 原版常用按键翻译表,给玩家友好显示
数据在客户端首帧 + 改键保存时由 bridge-mod 自动刷新。
"""
import json
import os

# 原版常用按键翻译键 → 中文(兜底;bridge-mod 导出的 display 字段优先)
KEY_NAMES_CN = {
    "key.forward": "前进", "key.back": "后退", "key.left": "左移", "key.right": "右移",
    "key.jump": "跳跃", "key.sneak": "潜行", "key.sprint": "疾跑(双击前进)",
    "key.attack": "攻击/挖掘", "key.use": "使用物品/放置方块",
    "key.drop": "丢弃物品", "key.inventory": "打开背包",
    "key.hotbar.1": "快捷栏 1", "key.hotbar.2": "快捷栏 2", "key.hotbar.3": "快捷栏 3",
    "key.hotbar.4": "快捷栏 4", "key.hotbar.5": "快捷栏 5",
    "key.swapOffhand": "交换副手", "key.screenshot": "截图",
    "key.togglePerspective": "切换视角", "key.chat": "打开聊天",
    "key.command": "打开命令", "key.advancements": "进度",
    "key.playerlist": "玩家列表", "key.socialInteractions": "社交互动",
    "key.smoothCamera": "平滑视角", "key.fullscreen": "全屏",
    "key.spectatorOutlines": "旁观者轮廓",
    "key.saveToolbarActivator": "保存快捷栏", "key.loadToolbarActivator": "加载快捷栏",
    "key.creativeCategoryMenu": "创造模式搜索", "key.pickItem": "选取方块",
    "key.mouseButtonLeft": "鼠标左键",
}

# GLFW 键码 → 按键名(给玩家显示用;未知显示 code)
KEYCODE_NAMES = {
    32: "空格", 256: "ESC", 257: "回车", 258: "Tab", 259: "退格",
    340: "左Shift", 341: "左Ctrl", 342: "左Alt", 344: "左Win",
    344: "左Win", 345: "右Win", 346: "菜单", 348: "右Shift",
    262: "→", 263: "←", 265: "↑", 264: "↓",
    280: "大写锁定", 283: "删除", 290: "Home", 291: "End",
    260: "插入", 268: "Home(小键盘)", 269: "End(小键盘)",
    330: "Insert", 327: "Delete", 335: "PgUp", 334: "PgDn",
}


def keycode_to_name(code: int) -> str:
    """GLFW 键码 → 可读按键名"""
    if code in KEYCODE_NAMES:
        return KEYCODE_NAMES[code]
    if 65 <= code <= 90:
        return chr(code)                      # A-Z
    if 48 <= code <= 57:
        return chr(code)                      # 0-9
    if 320 <= code <= 329:
        return f"F{code - 319}"               # F1-F10
    if 330 <= code <= 347:
        return f"F{code - 319}"               # F11 等
    return f"键{code}"


def bind_name(name: str) -> str:
    """翻译键 → 中文(未收录则原样返回)"""
    return KEY_NAMES_CN.get(name, name)


def _disp(act: dict) -> str:
    """操作显示名:优先 bridge-mod 翻译 API 导出的 display(mod 中文名自动覆盖),兜底本地表"""
    d = act.get("display")
    if d:
        return d
    return bind_name(act.get("name", "?"))


def load_keybindings(game_dir: str, instance: str) -> dict | None:
    """读实例 .bridge/keybindings.json;不存在返回 None"""
    p = os.path.join(game_dir, "versions", instance, ".bridge", "keybindings.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def query_by_key(data: dict, key_text: str) -> str:
    """按按键查询:该键绑了哪些操作(一键多操作会列出全部,含 mod)"""
    code = None
    t = key_text.strip().lower()
    if t.isdigit():
        code = int(t)
    else:
        for c, n in KEYCODE_NAMES.items():
            if n.lower() == t or n == key_text.strip():
                code = c
                break
        if code is None and len(t) == 1 and t.isalpha():
            code = ord(t.upper())
    if code is None:
        return f"无法识别按键: {key_text}(可用 空格/左Shift/W/32 等)"
    acts = data.get(str(code), [])
    if not acts:
        return f"键 [{keycode_to_name(code)}] 没有绑定任何操作"
    lines = [f"键 [{keycode_to_name(code)}] 绑定了 {len(acts)} 个操作:"]
    for a in acts:
        mod = "原版" if a.get("mod", "minecraft") == "minecraft" else f"mod:{a.get('mod')}"
        lines.append(f"  · {bind_name(a.get('name','?'))} ({mod})")
    return "\n".join(lines)


def query_by_action(data: dict, action: str) -> str:
    """按操作(功能)查询:要按哪个键。支持中文名/翻译键关键词"""
    hits = []
    action_l = action.strip().lower()
    for code, acts in data.items():
        for a in acts:
            name = a.get("name", "")
            cn = bind_name(name)
            if (action_l in name.lower() or action_l in cn.lower()
                    or action_l in a.get("mod", "").lower()):
                hits.append((code, a))
    if not hits:
        return f"没找到和「{action}」相关的按键(试试:前进/攻击/背包/JEI/疾跑)"
    lines = [f"和「{action}」相关的按键:"]
    for code, a in hits[:15]:
        mod = "原版" if a.get("mod", "minecraft") == "minecraft" else f"mod:{a.get('mod')}"
        lines.append(f"  · {bind_name(a.get('name','?'))} → 按 [{keycode_to_name(int(code))}] ({mod})")
    return "\n".join(lines)


def query_keybindings(game_dir: str, instance: str, query: str) -> str:
    """综合查询:输入是按键(空格/左Shift/W/32)→查该键绑的操作;
    输入是功能词(前进/攻击/背包/JEI)→查对应按键。"""
    data = load_keybindings(game_dir, instance)
    if data is None:
        return ("还没有按键数据:需要安装 bridge-mod 并进入一次游戏\n"
                "(进游戏后会自动导出 .bridge/keybindings.json,改键也会自动刷新)")
    if not query.strip():
        return "请输入:一个按键(如 空格/左Shift/W/32)或一个功能(如 前进/攻击/背包/JEI)"
    # 判断输入像是按键还是功能
    t = query.strip().lower()
    looks_key = (t.isdigit() or len(t) <= 4
                 or any(n.lower() == t for n in KEYCODE_NAMES.values())
                 or (len(t) == 1 and t.isalpha()))
    if looks_key:
        return query_by_key(data, query)
    return query_by_action(data, query)
