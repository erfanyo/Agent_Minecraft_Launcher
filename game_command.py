# -*- coding: utf-8 -*-
"""
给运行中的游戏发送指令(如 /summon zombie)。

两条通道,自动选择:
1. RCON(首选,干净可靠):实例目录 server.properties 里
   enable-rcon=true / rcon.port / rcon.password 配置好后,
   用 RCON 协议(TCP)像服务器控制台一样发命令。
   单人世界"对局域网开放"(ESC → 对局域网开放)后同样有效。
2. 模拟按键(通用兜底):找到游戏主窗口 → 置前 → 按 / 打开聊天框
   → 剪贴板粘贴命令 → 回车。支持中文,全屏/焦点被抢时可能不生效。

AI 工具用 RCON 通道(无 GUI 依赖);启动器 GUI 用完整智能选择。
"""
import os
import socket
import struct
import time

import ctypes  # Windows 专属模拟按键用;wintypes 在用到时延迟导入(非 Windows 无此子模块)

import paths


def _is_windows() -> bool:
    import sys
    return sys.platform.startswith("win")

# ================= RCON 协议(纯 socket,无第三方依赖) =================
# 包格式: [len:4][request_id:4][type:4][payload...][0x00][0x00]
RCON_AUTH = 3
RCON_EXEC = 2
RCON_AUTH_RESP = 2
RCON_RESP = 0


def rcon_execute(host: str, port: int, password: str, command: str,
                 timeout: float = 6.0) -> str:
    """发送一条 RCON 命令,返回服务器响应文本(截断 2000 字)。"""
    s = socket.create_connection((host, port), timeout=timeout)

    def _recv_exact(n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = s.recv(n - len(data))
            if not chunk:
                raise ConnectionError("RCON 连接被关闭")
            data += chunk
        return data

    def _send_packet(req_id: int, ptype: int, payload: str) -> str:
        body = struct.pack("<ii", req_id, ptype) + payload.encode("utf-8") + b"\x00\x00"
        s.sendall(struct.pack("<i", len(body)) + body)
        ln = struct.unpack("<i", _recv_exact(4))[0]
        if ln < 10:
            raise ConnectionError("RCON 响应过短")
        data = _recv_exact(ln)
        rid, rtype = struct.unpack("<ii", data[:8])
        text = data[8:-2].decode("utf-8", "replace")
        if rid == -1:
            raise PermissionError("RCON 认证失败(密码错误?)")
        return text

    try:
        _send_packet(1, RCON_AUTH, password)      # 认证
        return _send_packet(2, RCON_EXEC, command)  # 执行命令
    finally:
        s.close()


def read_rcon_config(inst_dir: str) -> dict | None:
    """读实例目录的 server.properties,返回 rcon 配置;
    未开启 enable-rcon 或文件不存在返回 None。"""
    path = os.path.join(inst_dir, "server.properties")
    if not os.path.isfile(path):
        return None
    props = {}
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    except Exception:
        return None
    if props.get("enable-rcon", "").lower() != "true":
        return None
    try:
        port = int(props.get("rcon.port", "25575"))
    except ValueError:
        port = 25575
    return {"port": port, "password": props.get("rcon.password", "")}


# ================= 模拟按键(Windows 专属,通用兜底) =================
def find_game_window(pid: int):
    """按进程 pid 找它的主窗口句柄(可见窗口)。仅 Windows;其它平台返回 None。"""
    if not _is_windows():
        return None
    from ctypes import wintypes
    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        tid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(tid))
        if tid.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            result.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(_cb, 0)
    return result[0] if result else None


def _key(vk: int, up: bool = False):
    if not _is_windows():
        return
    try:
        ctypes.windll.user32.keybd_event(vk, 0, 2 if up else 0, 0)
    except Exception:
        pass


def send_keys_to_game(hwnd, command: str):
    """把命令"打"进游戏:置前 → 开聊天框 → Ctrl+V 粘贴 → 回车。仅 Windows;其它平台无操作。"""
    if not _is_windows():
        return
    user32 = ctypes.windll.user32
    try:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.35)
        # 打开聊天框:按 /
        _key(0xBF)          # VK_OEM_2 = /
        _key(0xBF, up=True)
        time.sleep(0.25)
        # Ctrl+V 粘贴命令(含开头的 / 或直接命令文本)
        _key(0x11)          # Ctrl down
        _key(0x56)          # V
        _key(0x56, up=True)
        _key(0x11, up=True)
        time.sleep(0.15)
        # 回车发送
        _key(0x0D)          # Enter
        _key(0x0D, up=True)
    except Exception:
        pass


# ================= 日志增量反馈(命令执行结果) =================

def _log_line_count(inst_dir) -> int:
    """latest.log 当前行数(用作增量基线)"""
    log_path = os.path.join(inst_dir, "logs", "latest.log")
    if not os.path.isfile(log_path):
        return 0
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _log_tail_since(inst_dir, since_count: int) -> list:
    """读 latest.log 自 since_count 行之后的新增行(命令执行结果反馈)"""
    log_path = os.path.join(inst_dir, "logs", "latest.log")
    if not os.path.isfile(log_path):
        return []
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []
    return [ln.rstrip("\n") for ln in lines[since_count:]]


def _log_feedback(inst_dir, base_count: int, max_lines: int = 6) -> str:
    """发送命令后取日志增量,拼成反馈文本;没有新增内容返回空串"""
    if not inst_dir:
        return ""
    new = [l for l in _log_tail_since(inst_dir, base_count) if l.strip()]
    if not new:
        return ""
    shown = new[:max_lines]
    text = "\n📋 日志反馈(命令执行结果):\n" + "\n".join(l[:120] for l in shown)
    if len(new) > max_lines:
        text += "\n…(还有 %d 行)" % (len(new) - max_lines)
    return text


# ================= Lan Server Properties 联动(方案 A:免手动开放局域网) =================
# 该 mod(Modrinth slug: lan-server-properties)在"对局域网开放"时自动套用
# server.properties 的设置(含 RCON),配合启动器自动写配置 = 单人世界进图即自动开 RCON。

LAN_SERVER_PROPERTIES_SLUG = "lan-server-properties"

def has_lan_server_properties(inst_dir: str) -> bool:
    """实例 mods 目录是否装了 Lan Server Properties mod"""
    mods_dir = os.path.join(inst_dir, "mods")
    if not os.path.isdir(mods_dir):
        return False
    try:
        low = " ".join(f.lower() for f in os.listdir(mods_dir))
    except OSError:
        return False
    return "lan-server-properties" in low or "lanserverproperties" in low


def ensure_rcon_config(inst_dir: str, port: int = 25575) -> str:
    """检测到 Lan Server Properties → 自动写好 server.properties 开 RCON。
    幂等:已有配置不动(密码保留)。返回状态文本,供提示用户。"""
    if not has_lan_server_properties(inst_dir):
        return ("未检测到 Lan Server Properties mod。\n"
                "装上它(Modrinth 搜 lan-server-properties,支持 Forge/NeoForge/Fabric)后,\n"
                "启动器就能自动开 RCON,单人世界免手动'对局域网开放'。")
    path = os.path.join(inst_dir, "server.properties")
    props = {}
    if os.path.isfile(path):
        try:
            for line in open(path, encoding="utf-8", errors="replace"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
        except Exception:
            pass

    changed = []
    if props.get("enable-rcon") != "true":
        props["enable-rcon"] = "true"
        changed.append("enable-rcon=true")
    if props.get("rcon.port") != str(port):
        props["rcon.port"] = str(port)
        changed.append(f"rcon.port={port}")
    if not props.get("rcon.password"):
        import secrets
        props["rcon.password"] = secrets.token_hex(8)
        changed.append("rcon.password=已生成随机密码")

    if changed or not os.path.isfile(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                for k, v in props.items():
                    f.write(f"{k}={v}\n")
        except Exception as e:
            return f"写 server.properties 失败:{e}"
        return ("已自动配置 RCON(Lan Server Properties 生效):\n"
                + "\n".join(changed)
                + "\n\n接下来(必做):重启游戏 → 进世界后按 ESC → 点「对局域网开放」。\n"
                "Lan Server Properties 会在这一步自动应用配置并开启 RCON,之后发指令即直连。")
    return ("RCON 已配置好(Lan Server Properties):\n"
            "重启游戏 → 进世界按 ESC → 点「对局域网开放」后即可直接发指令。")


# ================= 智能发送(启动器 GUI 用) =================
def send_command(command: str, main_window) -> str:
    """给运行中的游戏发命令:先试 RCON,不行再模拟按键。
    发送后读日志增量作为执行反馈(weather rain 这类静默成功也有迹可循)。
    返回状态说明。main_window 需有 game_process / _running_instance_id / game_dir_for。"""
    cmd = command.strip()
    if not cmd:
        return "命令为空"
    if not cmd.startswith("/"):
        cmd = "/" + cmd

    game = getattr(main_window, "game_process", None)
    if game is None or game.poll() is not None:
        return "游戏没有在运行"
    inst_id = getattr(main_window, "_running_instance_id", None)
    inst_dir = main_window.game_dir_for(inst_id) if inst_id else None

    # 发送前基线:记录日志行数,发送后读增量当执行结果
    base_count = _log_line_count(inst_dir) if inst_dir else 0

    # 1) RCON 通道(没配置时尝试自动配置:装了 Lan Server Properties 就免手动开放局域网)
    sent = None
    guide = ""
    if inst_dir:
        rc = read_rcon_config(inst_dir)
        if rc is None:
            note = ensure_rcon_config(inst_dir)
            if "已自动配置" in note or "已配置好" in note:
                # 配置刚写好/已就绪:需要重新进入世界才生效,本次不发送
                return note
            guide = note   # 没装 mod:记录引导,下方走模拟按键兜底
            rc = read_rcon_config(inst_dir)
        if rc:
            try:
                out = rcon_execute("127.0.0.1", rc["port"], rc["password"], cmd)
                sent = f"✅ RCON 已发送:{cmd}\n服务器返回:{out[:200] if out else '(空,命令可能已静默执行成功)'}"
            except PermissionError:
                sent = "RCON 认证失败(密码可能被改过),改用模拟按键…"
            except ConnectionRefusedError:
                sent = ("RCON 拒绝连接(游戏未开放局域网或没装 Lan Server Properties),"
                        "改用模拟按键…\n" + _rcon_diagnosis(inst_dir))
            except Exception as e:
                sent = f"RCON 失败({e}),改用模拟按键…"

    # 2) 模拟按键(Windows 通用兜底;其它平台 RCON 失败时给说明)
    if sent is None:
        if not _is_windows():
            return ("当前平台不支持模拟按键发指令(仅 Windows)。\n"
                    "请用 RCON:装上 lan-server-properties mod 后进世界 → ESC → 对局域网开放。")
        pid = game.pid
        hwnd = find_game_window(pid)
        if not hwnd:
            return "找不到游戏窗口(可能最小化了,先还原窗口再试)"
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(cmd)
        try:
            send_keys_to_game(hwnd, cmd)
        except Exception as e:
            return f"模拟按键失败:{e}"
        sent = f"✅ 已向游戏发送(模拟按键):{cmd}"
        if guide:
            sent += "\n💡 " + guide.replace("\n", "\n   ")

    # 3) 等待并读取日志增量作为执行反馈
    time.sleep(0.9)
    fb = _log_feedback(inst_dir, base_count)
    return sent + (fb if fb else "\n(暂未观察到日志反馈,可能还在执行)")


def _rcon_diagnosis(inst_dir: str) -> str:
    """RCON 连接失败时,检查各项前置,给出"缺哪一步"的诊断"""
    lines = ["诊断:"]
    if has_lan_server_properties(inst_dir):
        lines.append("· ✅ 已检测到 Lan Server Properties mod")
    else:
        lines.append("· ❌ 未检测到 Lan Server Properties mod → 先一键配置(会自动下载)或手动装它")
    rc = read_rcon_config(inst_dir)
    if rc:
        lines.append(f"· ✅ server.properties 已配置 rcon(端口 {rc['port']})")
    else:
        lines.append("· ❌ server.properties 未配置 rcon → 点「一键配置 RCON」")
    lines.append("· ❓ 是否已:重启游戏 → 进世界 → 按 ESC → 点「对局域网开放」?"
                 "(RCON 只有在开放局域网后才会监听端口)")
    return "\n".join(lines)


# ================= bridge-mod 本地指令口(正式方案,优先) =================
# bridge-mod 进世界后监听 127.0.0.1:26100,并把 token 写到 .bridge/token.txt。
# 启动器读 token → 发 JSON 指令 → 收 JSON 结果(CommandSource 精确反馈)。

def send_bridge_command(instance: str, command: str, game_dir: str,
                        port: int = 26100, as_player: str = "") -> str:
    """走 bridge-mod 本地指令口发送指令(优先通道,100% 精确反馈)。
    port 默认 26100。as_player(可选):指定"以该在线玩家身份执行"(bridge-mod ≥ 协议 v2),
    如传玩家名或 UUID;留空 = 服务端控制台身份(默认,能用高级指令)。"""
    import json
    import socket
    inst_dir = paths.instance_dir(instance, game_dir)
    token_path = os.path.join(paths.bridge_dir(instance, game_dir), "token.txt")
    if not os.path.isfile(token_path):
        return ("bridge-mod 未运行或未装:进世界后它会在实例 .bridge/ 生成 token.txt。\n"
                "安装:启动器「我的版本 → 一键配置 ▾ → 一键配置 bridge-mod」")
    token = open(token_path, encoding="utf-8").read().strip()
    cmd = command.strip()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    # 双地址兜底:mod 绑 IPv4 127.0.0.1;旧版可能绑 ::1(IPv6 回环)
    conn = None
    for host in ("127.0.0.1", "::1"):
        try:
            conn = socket.create_connection((host, port), timeout=5)
            break
        except (ConnectionRefusedError, OSError):
            conn = None
            continue
    if conn is None:
        return ("指令口未监听:游戏没有在运行,或还没进入世界。\n"
                "请先启动游戏并进入一个世界(单机集成服务器运行时才有指令口),\n"
                "进入后立刻再让我发指令。")
    try:
        req = {"seq": 1, "command": cmd, "token": token}
        if as_player:
            req["as_player"] = as_player
        conn.sendall((json.dumps(req) + "\n").encode("utf-8"))
        resp = conn.recv(65536).decode("utf-8", "replace")
    except Exception as e:
        return f"bridge 通信失败:{e}"
    finally:
        conn.close()
    if not resp.strip():
        return "bridge 返回为空(命令可能已执行,无文本反馈)"
    data = json.loads(resp.splitlines()[0])
    ok = bool(data.get("success"))
    result = (data.get("result") or "").strip()
    head = f"✅ 已执行:{cmd}" if ok else f"⚠️ 命令可能失败:{cmd}"
    return head + ("\n" + result if result else "\n(无文本反馈)")


# ================= AI 工具版(RCON 通道,无 GUI 依赖) =================
def send_game_command(instance: str, command: str, game_dir: str) -> str:
    """给指定实例发命令(RCON),没配置时尝试自动配置(Lan Server Properties),
    并用日志增量补充反馈。"""
    inst_dir = paths.instance_dir(instance, game_dir)
    rc = read_rcon_config(inst_dir)
    if rc is None:
        note = ensure_rcon_config(inst_dir)
        if "已自动配置" in note or "已配置好" in note:
            return note + "\n\n重新进入世界后即可让我发指令。"
        return note   # 未装 mod:引导安装
    cmd = command.strip()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    base_count = _log_line_count(inst_dir)
    try:
        out = rcon_execute("127.0.0.1", rc["port"], rc["password"], cmd)
    except PermissionError:
        return ("错误:RCON 认证失败(密码不匹配)。\n"
                "可能是 server.properties 的 rcon.password 被改过,重新点「一键配置 RCON」即可。")
    except ConnectionRefusedError:
        return ("错误:RCON 拒绝连接——游戏没有在监听 RCON 端口。\n"
                + _rcon_diagnosis(inst_dir)
                + "\n\n替代方案:在启动器 AI 输入框直接输入 /" + cmd.lstrip("/")
                + "(走模拟按键通道,单人世界可用,无需 RCON)")
    except Exception as e:
        return f"错误:RCON 连接失败:{e}\n" + _rcon_diagnosis(inst_dir)
    time.sleep(0.9)
    fb = _log_feedback(inst_dir, base_count)
    head = f"已发送 {cmd}\n服务器返回:{out[:300] if out else '(空,命令可能已静默执行成功)'}"
    return head + (fb if fb else "\n(暂未观察到日志反馈)")
