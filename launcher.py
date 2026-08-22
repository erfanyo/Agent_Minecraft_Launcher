# -*- coding: utf-8 -*-
"""
启动器核心:把"版本 JSON"翻译成一条能运行的 Java 命令。

Minecraft 的启动原理:游戏本体是个 jar,"启动"就是用 Java 运行它,
并告诉它游戏目录、资源目录、账号信息等。这些"告诉"的内容以参数形式
写在版本 JSON 的 arguments 字段里,里面是 ${xxx} 占位符——
我们把占位符替换成真实值,就得到完整命令:

  java -Xmx2G ... -cp <依赖库+客户端jar> net.minecraft.client.main.Main
      --gameDir ... --assetsDir ... --username Player ...
"""
import json
import os
import re
import uuid

from downloader import download_with_mirror
from game_files import DEFAULT_FEATURES, library_entries, rules_allow

TOKEN_RE = re.compile(r"\$\{([^}]+)\}")


def load_version_json(version_id: str, game_dir: str) -> dict:
    """从磁盘读一个已安装版本的版本 JSON(versions/<id>/<id>.json)。

    启动器把每个版本的 JSON 存在它的实例目录里(自包含),
    Mojang 原版和 Fabric/Forge 版本都从这里读。
    """
    path = os.path.join(game_dir, "versions", version_id, version_id + ".json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _lib_key(lib: dict) -> str:
    """依赖库的去重键:优先 maven 名,其次下载路径"""
    return (lib.get("name")
            or ((lib.get("downloads") or {}).get("artifact") or {}).get("path", ""))


def _merge_libraries(parent_libs: list, child_libs: list) -> list:
    """合并依赖库:子版本的同名库覆盖父版本(标准继承规则),去掉重复。
    NeoForge 的 UnionFileSystem 对 classpath 里的重复 jar 会直接崩,必须去重。"""
    merged = {}
    for lib in list(parent_libs) + list(child_libs):
        key = _lib_key(lib)
        if key:
            merged[key] = lib          # 后出现的(子版本)覆盖先出现的(父版本)
        else:
            merged[f"__{id(lib)}"] = lib  # 没有名字的库按对象去重
    return list(merged.values())


def merge_version_json(parent: dict, child: dict) -> dict:
    """把子版本(如 Fabric/Forge/NeoForge)合并到父版本(原版)上,得到完整数据。

    规则:子覆盖父(id、mainClass 等);libraries 合并去重;arguments 合并。
    """
    merged = dict(parent)
    merged.update(child)
    merged["libraries"] = _merge_libraries(parent.get("libraries", []),
                                           child.get("libraries", []))
    if "arguments" in parent or "arguments" in child:
        p_args = parent.get("arguments", {}) or {}
        c_args = child.get("arguments", {}) or {}
        merged["arguments"] = {
            "game": list(p_args.get("game", [])) + list(c_args.get("game", [])),
            "jvm": list(p_args.get("jvm", [])) + list(c_args.get("jvm", [])),
        }
    return merged


def resolve_inherited_json(version_id: str, game_dir: str) -> dict:
    """递归解析继承链:Fabric/Forge 版本 JSON 里有 inheritsFrom 指向原版,
    一直合并到根(原版 JSON 必须已存在磁盘上)。"""
    data = load_version_json(version_id, game_dir)
    parent_id = data.get("inheritsFrom")
    if parent_id:
        parent = resolve_inherited_json(parent_id, game_dir)
        return merge_version_json(parent, data)
    return data


def replace_tokens(text: str, tokens: dict) -> str:
    """把字符串里的 ${名字} 全部替换成 tokens 里的值,找不到就替换成空串"""
    def sub(m):
        return str(tokens.get(m.group(1), ""))
    return TOKEN_RE.sub(sub, text)


def resolve_args(args_list: list, tokens: dict) -> list:
    """解析 arguments 列表:带规则的参数项按系统规则 + 功能开关过滤
    (和 libraries 同理),再把占位符替换成真实值。"""
    out = []
    for arg in args_list:
        if isinstance(arg, dict):
            # 演示模式/自定义分辨率/快速开始等开关我们都不开 → features 全 False
            if rules_allow(arg.get("rules"), DEFAULT_FEATURES):
                value = arg["value"]
                if isinstance(value, list):
                    out.extend(value)
                else:
                    out.append(value)
        else:
            out.append(arg)
    return [replace_tokens(a, tokens) for a in out]


def _resolve_logging(d: dict, game_dir: str) -> list:
    """下载日志配置文件(log4j),返回要加进命令的参数。
    失败就不加——日志配置不是启动的必需品,不能让它卡住启动。"""
    try:
        cfg = d.get("logging", {}).get("client")
        if not cfg or "file" not in cfg:
            return []
        info = cfg["file"]
        dest = os.path.join(game_dir, "assets", "log_configs", info["id"] + ".xml")
        if not (os.path.exists(dest) and os.path.getsize(dest) == info.get("size", 0)):
            download_with_mirror(info["url"], dest, sha1=info.get("sha1"))
        return [cfg.get("argument", "").replace("${path}", dest)]
    except Exception:
        return []


def build_launch_command(d: dict, game_dir: str, java_exe: str,
                         username: str = "Player", memory_gb: int = 2,
                         assets_dir: str | None = None,
                         install_dir: str | None = None) -> list:
    """把版本 JSON(d)翻译成完整的启动命令(列表形式,每项一个参数)。

    三个目录要分清:
    - game_dir    —— 游戏运行目录(--gameDir),版本隔离后每版本一个
    - assets_dir  —— 资源目录(所有版本共享,默认取 game_dir/assets 兼容旧行为)
    - install_dir —— 安装目录(libraries/客户端 jar/natives 所在,默认等于 game_dir)
    """
    version_id = d["id"]
    if install_dir is None:
        install_dir = game_dir

    # 1) classpath:所有依赖库 + 客户端 jar(游戏本体),都来自安装目录
    classpath = [os.path.join(install_dir, "libraries", p)
                 for p, _u, _s, _z in library_entries(d)]
    classpath.append(os.path.join(install_dir, "versions", version_id, f"{version_id}.jar"))
    classpath = list(dict.fromkeys(classpath))  # 去重兜底(NeoForge 的 UnionFileSystem 不允许重复)
    classpath_str = os.pathsep.join(classpath)

    # 2) natives 目录(现代版本原生库在 classpath 上,此目录供 java.library.path 用)
    natives_dir = os.path.join(install_dir, "versions", version_id, "natives")
    os.makedirs(natives_dir, exist_ok=True)

    # 3) 占位符的真实值
    if assets_dir is None:
        assets_dir = os.path.join(game_dir, "assets")
    assets_root = assets_dir
    tokens = {
        "auth_player_name": username,       # 离线账号名(账号体系在子步 E 完善)
        "auth_uuid": str(uuid.uuid4()),
        "auth_access_token": "0",           # 离线模式用 0 当令牌
        "auth_session": "0",
        "user_type": "legacy",
        "user_properties": "{}",
        "version_name": version_id,
        "version_type": d.get("type", "release"),
        "game_directory": game_dir,
        "assets_root": assets_root,
        "assets_index_name": (d.get("assetIndex") or {}).get("id", ""),
        "natives_directory": natives_dir,
        "library_directory": os.path.join(install_dir, "libraries"),
        "launcher_name": "AgentLauncher",
        "launcher_version": "0.1",
        "classpath": classpath_str,
        "classpath_separator": os.pathsep,
        "resolution_width": 854,
        "resolution_height": 480,
        "quickPlayPath": "",
    }

    # 4) JVM 参数:现代版本 JSON 自带一部分,我们再加上内存设置
    jvm = [f"-Xmx{memory_gb}G", "-XX:+UseG1GC"]
    if "arguments" in d:
        jvm += resolve_args(d["arguments"].get("jvm", []), tokens)
    else:
        # 老版本:没有 arguments 字段,自己拼最基础的参数
        jvm += ["-Djava.library.path=" + natives_dir, "-cp", classpath_str]

    # NeoForge 用模块路径(-p)启动:原版继承来的 -cp 会干扰模块解析,
    # 去掉它,classpath 改由 -DlegacyClassPath 传给 BootstrapLauncher
    if "-p" in jvm and "legacyClassPath" not in " ".join(jvm):
        cleaned = []
        skip_next = False
        for a in jvm:
            if skip_next:          # 丢掉 -cp 的值
                skip_next = False
                continue
            if a == "-cp":
                skip_next = True   # 丢掉 -cp 本身
                continue
            cleaned.append(a)
        jvm = cleaned
        jvm.append("-DlegacyClassPath=" + classpath_str)

    # 5) 日志配置参数(可有可无;配置文件属于资源,放共享资源目录)
    jvm += _resolve_logging(d, assets_root)

    # 6) 游戏参数
    if "arguments" in d:
        game_args = resolve_args(d["arguments"].get("game", []), tokens)
    else:
        game_args = replace_tokens(d.get("minecraftArguments", ""), tokens).split()

    return [java_exe] + jvm + [d["mainClass"]] + game_args
