# -*- coding: utf-8 -*-
"""实例扫描:读取 versions 目录,识别每个实例的加载器与基础版本。
独立成轻量模块,让 CLI / AI 工具 / GUI 都能用,不依赖 Qt。

识别依据(由强到弱):
1. 目录名 / JSON id / inheritsFrom 里的关键词(fabric/neoforge/forge)
2. libraries 里的 artifact 名(整合包常不写 inheritsFrom,但依赖里带加载器:
   net.neoforged.fancymodloader → neoforge;net.minecraftforge:eventbus → forge;
   net.fabricmc:fabric-loader → fabric)
3. mainClass(如 net.fabricmc.loader.impl.launch.knot.KnotClient / cpw.mods.bootstraplauncher)
4. 都没有 → 检查 mods 目录:有 jar 算"modded",否则原版
"""
import json
import os

import paths
from instance_metadata import read_metadata


def detect_running_instances(instance_dirs: dict[str, str]) -> set[str]:
    return {row['id'] for row in detect_running_clients(instance_dirs)}


def detect_running_clients(instance_dirs: dict[str, str], inspect_ports=False) -> list[dict]:
    """Read client launch arguments, including Java argument files used by launchers."""
    import psutil
    import shlex

    def normalized(value):
        return os.path.normcase(os.path.realpath(value.strip('"')))

    directories = {name: normalized(folder) for name, folder in instance_dirs.items()}
    running = []
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            if 'java' not in (process.info['name'] or '').lower():
                continue
            args = process.info['cmdline'] or []
            expanded = []
            for arg in args:
                if arg.startswith('@'):
                    filename = arg[1:].strip('"')
                    if not os.path.isabs(filename):
                        filename = os.path.join(process.cwd(), filename)
                    try:
                        with open(filename, encoding='utf-8-sig') as stream:
                            content = stream.read(1024 * 1024 + 1)
                        if len(content) <= 1024 * 1024:
                            expanded.extend(shlex.split(content, posix=False, comments=True))
                    except (OSError, UnicodeError, ValueError):
                        pass
                else:
                    expanded.append(arg)
            args = [arg.strip('"') for arg in expanded]
            for index in range(len(args) - 1, -1, -1):
                if args[index].startswith(('--gameDir=', '--version=')):
                    args[index:index + 1] = args[index].split('=', 1)
            # Servers and unrelated Java programs do not carry these client arguments.
            if '--gameDir' not in args or not any(
                    flag in args for flag in ('--version', '--assetsDir', '--assetIndex')):
                continue
            game_dir = args[args.index('--gameDir') + 1]
            version = args[args.index('--version') + 1] if '--version' in args else ''
            if not os.path.isabs(game_dir):
                game_dir = os.path.join(process.cwd(), game_dir)
            matching = [name for name, folder in directories.items()
                        if folder == normalized(game_dir)]
            instance_id = matching[0] if len(matching) == 1 else version if version in matching else None
            # PCL may use version isolation independently of AMCL's setting.
            if instance_id is None:
                candidate = os.path.basename(normalized(game_dir))
                for name, folder in directories.items():
                    if name.casefold() == candidate.casefold() and (
                            normalized(game_dir) == normalized(os.path.join(folder, 'versions', name))):
                        instance_id = name
                        break
            external = instance_id is None
            instance_id = instance_id or os.path.basename(normalized(game_dir)) or version
            row = {'id': instance_id, 'pid': process.pid,
                            'parent_pids': [parent.pid for parent in process.parents()],
                            'create_time': process.create_time(),
                            'game_dir': normalized(game_dir), 'external': external,
                            'name': instance_id + ('（外部启动）' if external else '')}
            if os.name == 'nt':
                from memory_relief import visible_game_window
                row['window_visible'] = visible_game_window(process.pid)
            if inspect_ports:
                row['lan_ports'] = []
                try:
                    for connection in process.net_connections(kind='tcp'):
                        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
                            continue
                        port = connection.laddr.port
                        host = connection.laddr.ip
                        if host in ('0.0.0.0', '::'):
                            host = '::1' if host == '::' else '127.0.0.1'
                        if port not in row['lan_ports'] and _minecraft_status_available(host, port):
                            row['lan_ports'].append(port)
                except (psutil.Error, OSError):
                    row['port_detection_unavailable'] = True
            running.append(row)
        except (psutil.Error, OSError, IndexError, ValueError):
            continue
    # Some Java launch wrappers retain the full client arguments while a child
    # owns the game window. Keep independent launches, but remove their wrappers.
    return [row for row in running if not any(
        row['pid'] in child['parent_pids'] and row['game_dir'] == child['game_dir']
        for child in running if child['pid'] != row['pid'])]


def _minecraft_status_available(host, port):
    """Verify a Java Edition status response, rather than treating any listener as LAN."""
    import socket
    import struct

    def varint(value):
        result = bytearray()
        while value >= 128:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
        return bytes(result)

    try:
        with socket.create_connection((host, port), timeout=0.4) as stream:
            stream.settimeout(0.4)
            address = host.encode('utf-8')
            handshake = b'\x00' + varint(47) + varint(len(address)) + address + struct.pack('>H', port) + b'\x01'
            stream.sendall(varint(len(handshake)) + handshake + b'\x01\x00')

            def read_varint():
                value = 0
                for shift in range(0, 35, 7):
                    byte = stream.recv(1)
                    if not byte:
                        raise ValueError('Incomplete packet')
                    value |= (byte[0] & 127) << shift
                    if not byte[0] & 128:
                        return value
                raise ValueError('Invalid packet')

            packet_size = read_varint()
            if not 0 < packet_size <= 256 * 1024 or read_varint() != 0:
                return False
            size = read_varint()
            if not 0 < size <= packet_size:
                return False
            payload = bytearray()
            while len(payload) < size:
                chunk = stream.recv(min(4096, size - len(payload)))
                if not chunk:
                    return False
                payload.extend(chunk)
            response = json.loads(payload.decode('utf-8'))
            return isinstance(response, dict) and 'version' in response and 'players' in response
    except (OSError, ValueError, UnicodeError):
        return False


def find_instance_version_json(folder: str, instance_id: str) -> str | None:
    """Find the launch JSON in a manually copied instance folder.

    Standard instances use <folder>/<folder>.json. Third-party launchers often keep
    the loader profile name after the user renames the containing folder. Accept a
    single unambiguous launch JSON without treating metadata JSON as a version.
    """
    exact = os.path.join(folder, instance_id + '.json')
    if os.path.isfile(exact):
        return exact
    candidates = []
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    ignored = {'amcl_instance.json', 'launch_options.json', 'modrinth.index.json',
               'manifest.json', 'mmc-pack.json'}
    for filename in names:
        if not filename.lower().endswith('.json') or filename.lower() in ignored:
            continue
        path = os.path.join(folder, filename)
        try:
            with open(path, encoding='utf-8') as file:
                data = json.load(file)
            if isinstance(data, dict) and any(key in data for key in
                                              ('mainClass', 'libraries', 'inheritsFrom', 'downloads')):
                candidates.append(path)
        except (OSError, ValueError, TypeError):
            continue
    return candidates[0] if len(candidates) == 1 else None


def _base_from_launch_arguments(data: dict) -> str:
    args = (data.get('arguments') or {}).get('game') or []
    flat = [str(value) for value in args if isinstance(value, (str, int, float))]
    for flag in ('--fml.mcVersion', '--fml.mcversion'):
        for index, value in enumerate(flat[:-1]):
            if value.lower() == flag.lower():
                return flat[index + 1]
    return ''


def _detect_loader(name: str, data: dict) -> str | None:
    """综合判断加载器,返回 fabric/neoforge/forge/None(认不出)"""
    # 1) 名称关键词(注意 neoforge 含子串 forge,必须先匹配长的)
    low = (str(name) + " " + str(data.get("id", ""))
           + " " + str(data.get("inheritsFrom", ""))).lower()
    for l in ("fabric", "neoforge", "forge"):
        if l in low:
            return l
    # 2) libraries 里的 artifact 名(整合包常见:不写 inheritsFrom,但带加载器依赖)
    for lib in data.get("libraries", []) or []:
        n = str(lib.get("name", "")).lower()
        if "fabricmc" in n or "fabric-loader" in n:
            return "fabric"
        if "neoforged" in n or "neoforge" in n:
            return "neoforge"
        if "minecraftforge" in n:
            return "forge"
    # 3) mainClass
    mc = str(data.get("mainClass", "")).lower()
    if "fabricmc" in mc:
        return "fabric"
    if "neoforge" in mc:
        return "neoforge"
    if "cpw.mods" in mc or "fml" in mc or "forge" in mc:
        return "forge"
    return None


def scan_instances(game_dir: str = None) -> list:
    """扫描已安装的实例及手动复制进 versions 的单入口实例。
    返回 [{id, base, loader, label}],loader 为 fabric/forge/neoforge/'modded'/None(原版)
    game_dir 缺省时用当前生效的游戏目录(paths.GAME_DIR,设置里可改)。"""
    if game_dir is None:
        game_dir = paths.GAME_DIR
    instances = []
    versions_dir = os.path.join(game_dir, "versions")
    if not os.path.isdir(versions_dir):
        return instances
    for name in sorted(os.listdir(versions_dir)):
        if name.startswith("_"):
            continue   # 版本仓库(_versions/ 等),不是实例
        if os.path.isfile(os.path.join(versions_dir, '_imports', name + '.json')):
            continue  # 尚未完成的导入不能作为可启动实例。
        folder = os.path.join(versions_dir, name)
        vjson = find_instance_version_json(folder, name)
        if not vjson:
            continue
        try:
            with open(vjson, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        metadata = read_metadata(folder)
        base = (metadata.get('minecraft_version') or data.get("inheritsFrom") or
                data.get('clientVersion') or _base_from_launch_arguments(data))
        has_base = bool(data.get('inheritsFrom'))
        loader = metadata['loader'] if 'loader' in metadata else _detect_loader(name, data)
        if not base:
            base = name
        if loader is None:
            if has_base:
                # 有继承链但认不出具体加载器:至少不是原版(原版 json 没有 inheritsFrom)
                loader = "modded"
            else:
                # 认不出加载器:有 mods 目录且含 jar → 至少算 modded,不算原版
                mods_dir = os.path.join(versions_dir, name, "mods")
                if os.path.isdir(mods_dir):
                    try:
                        if any(f.endswith(".jar") for f in os.listdir(mods_dir)):
                            loader = "modded"
                    except OSError:
                        pass
        display = str(metadata.get('display_name') or name)
        label = f"{display}  ({loader or '原版'} ← {base})"
        instances.append({"id": name, "name": display, "base": base, "loader": loader, "label": label})
    return instances
