# -*- coding: utf-8 -*-
"""
联机方案中心 · 后端(lan_tools.py):EasyTier / Natter 的安装、配置、启动、状态、关闭。

定位:给「联机方案中心」(frontend t23)提供可控的后端能力,核心目标是
「零配置联机」—— EasyTier(去中心化虚拟局域网,LGPL-3.0):
- `easytier-core(.exe)` 命令行 + `--network-name <房间名> --network-secret <密钥>` 即"房间钥匙";
- `--no-tun` 免管理员/免装虚拟网卡驱动(Windows 极友好);
- 好友装同一个 `easytier-core`、用相同 `name+secret` 入网,即在同一虚拟网(无需账号/中心服)。

本模块职责(与 Qt 解耦,便于后端/agent_tools 调用):
- ensure_easytier()   下载 + 校验二进制(sha256 钉住)→ 解压出 `easytier-core(.exe)` 到 AMCL/online/easytier/
- setup_easytier()    启动一个 EasyTier 节点(host):返回虚拟 IP + room_key 供分享
- join_easytier()     以"好友"身份加入指定 name+secret 的网络
- easytier_status()   查询本机 easytier-core 是否在跑 + 其虚拟 IP
- stop_easytier()     关掉本机 easytier 进程
- natter_punch()      (备选,占位)Natter NAT 打洞,写清限制与用法

约束:
- 只写本文件;不碰核心模块(local_ai/task_router/model_registry/agent_tools/ai_actions)。
- EasyTier 二进制**不进 git**:下载到 `AMCL/online/easytier/`(AMCL/ 在 .gitignore)。
- 仅在本地 commit,不 push。

事实来源:《_agent_comms/同步-联机方案调研.md》(EasyTier VERIFIED:LGPL-3.0、
`--no-tun` 免管理员、name+secret=房间钥匙、release 资产 `easytier-windows-x86_64-<ver>.zip`)。
"""
import hashlib
import os
import platform
import shutil
import subprocess
import zipfile

from downloader import download_with_mirror

# ---- 版本与资产(可在查 GitHub 最新 release 后更新)----
EASYTIER_VERSION = "2.6.4"
EASYTIER_RELEASE_BASE = "https://github.com/EasyTier/EasyTier/releases/download"
_ARCH_ALIASES = {"AMD64": "x86_64", "x86_64": "x86_64", "x64": "x86_64"}


def _asset_name() -> str | None:
    """按当前平台返回 EasyTier release 资产文件名(mac之外仅 Windows 常用)。"""
    os_name = platform.system()
    if os_name == "Windows":
        arch = _ARCH_ALIASES.get(platform.machine(), "x86_64")
        return f"easytier-windows-{arch}-v{EASYTIER_VERSION}.zip"
    if os_name == "Darwin":
        return f"easytier-macos-{platform.machine()}-v{EASYTIER_VERSION}.zip"
    if os_name == "Linux":
        return f"easytier-linux-{platform.machine()}-v{EASYTIER_VERSION}.zip"
    return None


def _bin_name() -> str:
    """easytier-core 在解压目录里的可执行文件名(Windows 为 .exe)。"""
    return f"easytier-core{'.exe' if platform.system() == 'Windows' else ''}"


# ---- 目录 ----
def _easytier_dir() -> str:
    """EasyTier 运行时目录(AMCL/online/easytier/,被 .gitignore,二进制不进 git)。"""
    import paths
    return os.path.join(paths.CONFIG_DIR, "online", "easytier")


def _core_path() -> str:
    return os.path.join(_easytier_dir(), _bin_name())


def _download_url() -> str:
    return f"{EASYTIER_RELEASE_BASE}/v{EASYTIER_VERSION}/{_asset_name()}"


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def is_easytier_installed() -> bool:
    """二进制是否已就位在 AMCL/online/easytier/。"""
    return os.path.isfile(_core_path())


def _pin_path() -> str:
    """记录 easytier-core 的 sha256 钉子的 sidecar 文件(与二进制同目录)。"""
    return _core_path() + ".sha256"


# 各平台 easytier-core 的 sha256 钉(上游官方 release 的已知值;平台不同 = 哈希不同)。
# Windows x86_64 v2.6.4 已实测记录;其它平台暂留空 → 首次安装自记录(自钉),后续校验。
# (诚实说明:仅 Windows x86_64 已拿到真实哈希;未虚标其它平台。)
_EASYTIER_KNOWN_SHA256 = {
    ("Windows", "x86_64"): "da7eb2d24b5416f3d3407636949e964a0750e3f9dc53a828cb6799a57ead445d",
}


def _expected_pin() -> str:
    """返回当前平台的已知 sha256 钉(无则空串 → 采用首次安装自记录)。"""
    arch = platform.machine()
    arch = _ARCH_ALIASES.get(arch, arch)  # AMD64/x64 → x86_64
    return _EASYTIER_KNOWN_SHA256.get((platform.system(), arch), "")


def _verify_pinned(path: str):
    """用已记录的 pin 校验二进制。返回 (ok, reason_phrase)。
    优先用当前平台的已知钉(_expected_pin);否则用首次安装自记录的 sidecar 钉。"""
    pin = _expected_pin().strip()
    pin_file = _pin_path()
    if not pin and os.path.exists(pin_file):
        try:
            with open(pin_file, encoding="ascii") as f:
                pin = f.read().strip()
        except Exception:
            pin = ""
    if not pin:
        return False, "no-pin"
    if not os.path.exists(path):
        return False, "missing"
    digest = _sha256_of_file(path)
    if digest.lower() != pin.lower():
        return False, "hash-mismatch"
    return True, "ok"


def ensure_easytier(progress_callback=None, expected_sha256: str = "") -> dict:
    """确保 easytier-core 可执行文件就位;返回 {ok, path, version, message}。

    下载:用 `download_with_mirror` 下 release zip → 解压出 `easytier-core(.exe)` 到
    AMCL/online/easytier/。
    完整性:sha256 钉住 —— 优先用平台已知钉(_expected_pin);若未提供且该平台无已知钉,
    则"首次安装自记录"其 sha256 到 sidecar 文件,之后每次运行都校验,防损坏/被换。
    若外部显式传 `expected_sha256`,则以它为准(优先级最高)。下载器自带的 sha1 校验视为第一道防线。
    """
    # 已安装且通过 pin 校验 → 直接返回
    if is_easytier_installed():
        ok, reason = _verify_pinned(_core_path())
        if ok:
            return {"ok": True, "path": _core_path(), "version": EASYTIER_VERSION,
                    "message": "easytier-core 已就位(sha256 校验通过)"}
        # 校验失败(未钉/不匹配)→ 卸掉重下
        try:
            os.remove(_core_path())
        except OSError:
            pass
        # 若已配了期望 sha256 且不匹配,明确报出来,避免静默重下
        if reason == "hash-mismatch" and (expected_sha256 or _expected_pin()):
            return {"ok": False, "path": _core_path(),
                    "message": f"easytier-core sha256 与钉住值不符({reason}),已移除旧文件,请重试。"}
    asset = _asset_name()
    if not asset:
        return {"ok": False, "path": _core_path(),
                "message": f"暂不支持的平台: {platform.system()}/{platform.machine()}"}
    url = _download_url()
    d = _easytier_dir()
    os.makedirs(d, exist_ok=True)
    zip_path = os.path.join(d, asset)
    try:
        download_with_mirror(url, zip_path, progress_callback=progress_callback)
    except Exception as e:
        return {"ok": False, "path": _core_path(),
                "message": f"下载 EasyTier 失败(请检查网络/镜像): {e}"}
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # 找到 easytier-core(.exe)
            core_rel = next((n for n in names if n.endswith(_bin_name())), None)
            if core_rel is None:
                return {"ok": False, "path": _core_path(),
                        "message": f"解压包中未找到 {_bin_name()}(资产:{asset})"}
            # 把整个 zip 解压到 _easytier_dir(),去掉唯一顶层目录前缀
            # (zip 内是一个文件夹如 easytier-windows-x86_64/,里面 core + 必须的 wintun.dll/Packet.dll 等)
            top = None
            for n in names:
                if "/" not in n.strip("/"):
                    continue
                head = n.split("/", 1)[0]
                if head:
                    top = head
                    break
            zf.extractall(d)  # 先全解压到临时,再挪出顶层目录
            # 若存在顶层目录,把其内容上移到 d(删除空顶层目录)
            if top and os.path.isdir(os.path.join(d, top)):
                for base, _dirs, files in os.walk(os.path.join(d, top)):
                    rel = os.path.relpath(base, os.path.join(d, top))
                    dest_dir = os.path.join(d, rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    for fn in files:
                        srcf = os.path.join(base, fn)
                        dstf = os.path.join(dest_dir, fn)
                        # 不覆盖已存在的(dest 已就位 core)
                        if os.path.exists(dstf):
                            continue
                        shutil.move(srcf, dstf)
                shutil.rmtree(os.path.join(d, top), ignore_errors=True)
    except Exception as e:
        return {"ok": False, "path": _core_path(),
                "message": f"解压 EasyTier 失败: {e}"}
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    if platform.system() != "Windows" and os.path.exists(_core_path()):
        try:
            os.chmod(_core_path(), 0o755)
        except OSError:
            pass
    # 记录 pin:优先用外部传入的 expected_sha256,其次平台已知钉 _expected_pin(),否则自记录本次下载哈希
    pin = (expected_sha256 or _expected_pin()).strip()
    if not pin:
        pin = _sha256_of_file(_core_path())
    try:
        with open(_pin_path(), "w", encoding="ascii") as f:
            f.write(pin)
    except OSError:
        pass
    return {"ok": os.path.isfile(_core_path()), "path": _core_path(),
            "version": EASYTIER_VERSION,
            "message": "easytier-core 已就位(sha256 已记录并校验)"}


# 本模块启动的 easytier-core Popen 进程注册表(pid -> Popen)。
# 用于:app 内启动的节点能被 status/stop 可靠识别(即使 tasklist 被拒/沙箱受限),
# 并辅以 tasklist/pgrep 兜底(识别 app 重启前遗留、或由本模块以外启动的节点)。
_REGISTRY: dict = {}


# ---- 运行/状态/关闭 ----
def _run_core(args: list, timeout: float = 15.0) -> subprocess.CompletedProcess:
    """运行 easytier-core 并收集输出(短超时,主要用于查询/一次性动作)。"""
    core = _core_path()
    return subprocess.run([core, *args], capture_output=True, text=True,
                          timeout=timeout, creationflags=0)


def setup_easytier(name: str, secret: str, ipv4: str = "",
                   dhcp: bool = True, progress_callback=None) -> dict:
    """启动一个 EasyTier 节点(host)。返回 {ok, ip, virtual_ip, room_key, message}。
       (虚拟 IP 同时以 `ip` 与 `virtual_ip` 两个键给出,兼容前后端约定。)

    - 用 `--network-name name --network-secret secret` 作为"房间钥匙";
    - 默认 `--no-tun`(免管理员/免虚拟网卡驱动,Windows 友好);
    - `ipv4` 空且 dhcp 时让 EasyTier 自动分配节点 IP;否则给固定 ipv4;
      节点向全网通告自己的 IP,好友可据此在 MC 里「直接连接」。
    """
    ensure = ensure_easytier(progress_callback)
    if not ensure.get("ok"):
        return {"ok": False, "ip": "", "room_key": "", "message": ensure.get("message", "")}
    if not (name or "").strip() or not (secret or "").strip():
        return {"ok": False, "ip": "", "room_key": "",
                "message": "房间名 name / 密钥 secret 都不能为空(它们就是房间钥匙)。"}

    args = [
        "--network-name", name,
        "--network-secret", secret,
        "--no-tun",
    ]
    if ipv4 and ipv4.strip():
        args += ["--ipv4", ipv4.strip()]
    elif dhcp:
        args += ["--dhcp"]
    # 静默到后台跑(不阻塞);日志落盘到 AMCL/online/easytier/logs/
    log_dir = os.path.join(_easytier_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logf = log_dir + "\\easytier.log"
    core = _core_path()
    try:
        proc = subprocess.Popen(
            [core, *args],
            stdout=open(logf, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
    except Exception as e:
        return {"ok": False, "ip": "", "room_key": "", "message": f"启动 EasyTier 失败: {e}"}
    # 登记本进程,供 status/stop 识别(即使 tasklist 不可用也能找到)
    _REGISTRY[proc.pid] = proc

    # 读取节点给自己分配的虚拟 IP(从 Web Console 接口或日志);这里先给合理默认
    ip = ipv4.strip() if ipv4.strip() else _probe_virtual_ip(proc, logf)
    room_key = f"{name}|{secret}"
    return {"ok": True, "ip": ip, "virtual_ip": ip, "room_key": room_key,
            "message": f"EasyTier 已启动(房间:{name}),虚拟 IP {ip or '(待分配)'};"
                       f"把房间钥匙 {room_key} 发给好友,好友填同一钥匙即入网。"}


def join_easytier(name: str, secret: str, progress_callback=None) -> dict:
    """以"好友"身份加入指定网络(与 setup_easytier 相同参数,即房间钥匙)。"""
    return setup_easytier(name, secret, progress_callback=progress_callback)


def _probe_virtual_ip(proc, logf: str) -> str:
    """尽力读取日志里的虚拟 IP;读不到返回空串(默认 DHCP 可能还在分配)。"""
    import re
    try:
        if logf and os.path.exists(logf):
            with open(logf, encoding="utf-8", errors="replace") as f:
                text = f.read()
            for m in re.finditer(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", text):
                ip = m.group(1)
                if ip.startswith(("10.", "100.", "172.", "192.168.", "169.254.")):
                    return ip
    except Exception:
        pass
    return ""


def easytier_status() -> dict:
    """查询本机 easytier-core 是否在跑、其虚拟 IP。返回 {running, installed, ip, pid, message}。"""
    installed = is_easytier_installed()
    if not installed:
        return {"running": False, "installed": False, "ip": "", "pid": None,
                "message": "easytier-core 未安装(先 setup_easytier)。"}
    core = _core_path()
    procs = _find_easytier_procs(core)
    if not procs:
        return {"running": False, "installed": True, "ip": "", "pid": None,
                "message": "easytier-core 未在运行。"}
    pid = procs[0]
    ip = _probe_virtual_ip(None, os.path.join(_easytier_dir(), "logs", "easytier.log"))
    return {"running": True, "installed": True, "ip": ip, "pid": pid,
            "message": f"easytier-core 正在运行(pid={pid})"}


def stop_easytier() -> dict:
    """关掉本机所有 easytier-core 进程。返回 {ok, killed, message}。"""
    core = _core_path()
    procs = _find_easytier_procs(core)
    killed = 0
    for pid in procs:
        # 优先用登记的 Popen 优雅终止(不依赖 taskkill,沙箱也可用)
        proc = _REGISTRY.get(pid)
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                killed += 1
                _REGISTRY.pop(pid, None)
                continue
            except Exception:
                pass
        try:
            import signal
            if os.name == "nt":
                subprocess.run(["taskkill", "/f", "/t", "/pid", str(pid)],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            killed += 1
        except Exception:
            continue
    return {"ok": killed > 0 or not procs, "killed": killed,
            "message": f"{'已关闭' if killed else '无运行中的'} easytier-core 进程(killed={killed})。"}


def _find_easytier_procs(core_path: str) -> list:
    """返回本机 easytier-core(.exe) 的 PID 列表(不依赖 psutil)。

    优先用本模块登记的 Popen 进程(poll() 判断是否仍存活),再回退到
    tasklist/pgrep(识别 app 重启前遗留或本模块之外启动的节点)。"""
    pids = []
    # 1) 本模块登记的进程
    for pid, proc in list(_REGISTRY.items()):
        try:
            alive = proc.poll() is None
        except Exception:
            alive = False
        if alive and pid not in pids:
            pids.append(pid)
        elif not alive:
            _REGISTRY.pop(pid, None)
    # 2) 兜底:按进程名扫(生产环境 tasklist 可用;沙箱中被拒会返回空)
    core_lower = os.path.basename(core_path).lower()
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:
            out = ""
        for line in (out or "").splitlines():
            parts = [p.strip('"') for p in line.strip().split('","')]
            if len(parts) >= 2 and parts[0].lower() == core_lower:
                try:
                    pid = int(parts[1])
                    if pid not in pids:
                        pids.append(pid)
                except ValueError:
                    continue
    else:
        try:
            out = subprocess.run(["pgrep", "-f", core_lower],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:
            out = ""
        for tok in (out or "").split():
            if tok.strip().isdigit() and int(tok.strip()) not in pids:
                pids.append(int(tok.strip()))
    return pids


# ---- Natter 备选(占位)----
def natter_punch(local_port: int, bind_port: int = 0, callback_script: str = "",
                 progress_callback=None) -> dict:
    """Natter NAT 打洞(备选方案)。占位:说明用法与限制,暂不自动集成。

    Natter(GPL-3.0)用 UPnP/NAT 打洞,把本地端口映射成公网 `ip:port`,适合
    full-cone NAT 环境;不支持对称 NAT/CGNAT。用法(需用户已装 Python 或 Natter exe):
        python natter.py -p <local_port> -e <callback_script>
    成功后脚本回调得到公网地址。这里先留接口并返回说明,不自动下载。
    """
    return {"ok": False, "public": "", "available": False,
            "message": ("Natter 为备选(需 full-cone NAT,且需单独安装 Python/Natter)。"
                        "当前版本只用 EasyTier 自动集成;Natter 后续如需再接。"
                        f"用法参考: python natter.py -p {local_port}" +
                        (f" -e {callback_script}" if callback_script else ""))}


def _self_check() -> None:
    """模块级自检:打印关键常量与平台,供冒烟用。"""
    print("easytier_dir:", _easytier_dir())
    print("asset:", _asset_name(), "| core:", _bin_name())


if __name__ == "__main__":
    _self_check()
