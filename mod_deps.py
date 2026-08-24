# -*- coding: utf-8 -*-
"""
Mod 依赖网络解析(离线,读 jar 元数据)——「谁依赖谁」一张图看明白。

数据来源(纯本地解析,不联网):
- Fabric:jar 内 `fabric.mod.json` 的 `id/name` + `depends`(required)/`suggests`(optional)/`breaks`(incompatible)
- NeoForge / Forge:`META-INF/neoforge.mods.toml` 或 `META-INF/mods.toml` 的 `[[mods]]`(modId/displayName)
  + `[[dependencies.<modid>]]`(type=required/optional/incompatible, versionRange)

产出:一个 `ModGraph`(节点=mod,边=依赖关系),支持正向(我依赖谁)/反向(谁依赖我)/缺失依赖查找。

无 GUI 依赖,CLI / 测试 / GUI 共用。
"""
import os
import zipfile


# 依赖类型
REQUIRED = "required"
OPTIONAL = "optional"
INCOMPATIBLE = "incompatible"

# 平台/加载器伪依赖:这些是环境自带,不是"真实 mod 对 mod"的关系,过滤掉免得图里一堆噪音。
# 注意保留 fabric-api(它是真正的 Fabric API mod,id 为 fabric-api)。
_PLATFORM_IDS = {
    "minecraft", "fabricloader", "fabric", "forge", "neoforge",
    "quilt_loader", "quilt", "java", "default",
}


class ModNode:
    __slots__ = ("mod_id", "file", "name", "loader", "version", "enabled", "missing")

    def __init__(self, mod_id, file="", name="", loader="", version="",
                 enabled=True, missing=False):
        self.mod_id = mod_id
        self.file = file                      # jar 文件名(缺失依赖时为 "")
        self.name = name or mod_id            # 显示名
        self.loader = loader
        self.version = version
        self.enabled = enabled                # True / 禁用(.jar.disabled)
        self.missing = missing                # 被引用但未安装的节点

    def __repr__(self):
        return f"<ModNode {self.mod_id} enabled={self.enabled} missing={self.missing}>"


class ModEdge:
    __slots__ = ("source", "target", "type", "version_range")

    def __init__(self, source, target, type, version_range=""):
        self.source = source                  # 谁声明依赖(mod id)
        self.target = target                  # 依赖谁(mod id;缺失依赖时 target 可能是平台 id 之外的未安装 mod)
        self.type = type
        self.version_range = version_range

    def __repr__(self):
        return f"<ModEdge {self.source} -[{self.type}]-> {self.target}>"


class ModGraph:
    def __init__(self):
        self.nodes = {}      # mod_id -> ModNode
        self.edges = []      # [ModEdge]
        self.info = []      # 解析过程中的非致命提示(如某 jar 无法识别)

    # ---- 构建 ----
    def add_node(self, node):
        cur = self.nodes.get(node.mod_id)
        if cur is None:
            self.nodes[node.mod_id] = node
            return
        # 缺失占位节点 -> 被真正安装的 mod 覆盖(以真实信息为准)
        if cur.missing and not node.missing:
            self.nodes[node.mod_id] = node
            return
        # 同名已有节点:优先保留已启用、信息更全的那个
        if node.enabled and not cur.enabled:
            self.nodes[node.mod_id] = node

    def add_edge(self, source, target, type, version_range=""):
        self.edges.append(ModEdge(source, target, type, version_range))

    def ensure_missing(self, mod_id, source_loader=""):
        if mod_id not in self.nodes:
            self.add_node(ModNode(mod_id, missing=True, loader=source_loader))

    # ---- 查询 ----
    def dependencies(self, mod_id) -> list:
        """我依赖谁 (target 列表)"""
        return [e for e in self.edges if e.source == mod_id]

    def dependents(self, mod_id) -> list:
        """谁依赖我 (source 列表)"""
        return [e for e in self.edges if e.target == mod_id]

    def missing_deps(self) -> list:
        """指向「未安装」节点的依赖边(= 装了 A 但缺 B 的警告)"""
        return [e for e in self.edges if e.target in self.nodes and self.nodes[e.target].missing]

    def stats(self) -> dict:
        return {"mods": len([n for n in self.nodes.values() if not n.missing]),
                "missing": len([n for n in self.nodes.values() if n.missing]),
                "edges": len(self.edges)}


# ---------- 单 jar 元数据读取 ----------

def _read_zip(zf, name):
    try:
        return zf.read(name)
    except (KeyError, OSError):
        return None


def _read_fabric_mod(zf):
    """读 fabric.mod.json → {loader, id, name, version, deps:[(modid,type,range)]} 或 None"""
    raw = _read_zip(zf, "fabric.mod.json")
    if raw is None:
        return None
    try:
        import json
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    deps = []
    for modid, rng in (data.get("depends") or {}).items():
        deps.append((modid, REQUIRED, str(rng or "*")))
    for modid, rng in (data.get("suggests") or {}).items():
        deps.append((modid, OPTIONAL, str(rng or "*")))
    for modid, rng in (data.get("breaks") or {}).items():
        deps.append((modid, INCOMPATIBLE, str(rng or "*")))
    return {"loader": "fabric", "id": str(data["id"]), "name": str(data.get("name") or data["id"]),
            "version": str(data.get("version") or ""), "deps": deps}


def _read_mods_toml(zf, name):
    """读 mods.toml / neoforge.mods.toml → 同上格式 或 None"""
    raw = _read_zip(zf, name)
    if raw is None:
        return None
    try:
        import tomllib
        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None
    mods = data.get("mods") or []
    if not mods:
        return None
    main = mods[0]
    modid = str(main.get("modId") or "")
    if not modid:
        return None
    # 收集所有 [[dependencies.<modid>]] 条目(有些 jar 会打包多个 mod);以主 mod 为节点
    deps = []
    for dep_owner, groups in (data.get("dependencies") or {}).items():
        for g in groups:
            if not isinstance(g, dict) or not g.get("modId"):
                continue
            t = str(g.get("type") or "required").lower()
            if "incompat" in t:
                t = INCOMPATIBLE
            elif "optional" in t or "soft" in t:
                t = OPTIONAL
            else:
                t = REQUIRED
            deps.append((str(g["modId"]), t, str(g.get("versionRange") or "*")))
    return {"loader": "neoforge" if "neoforge" in name else "forge",
            "id": modid, "name": str(main.get("displayName") or main.get("name") or modid),
            "version": str(main.get("version") or ""), "deps": deps}


def read_mod_metadata(jar_path: str) -> dict | None:
    """读一个 jar 的 mod 元数据,返回 {loader,id,name,version,deps:[(modid,type,range)]};
    识别不出(非 mod / 损坏)→ None。jar_path 可能带 .disabled(那也只是改名,仍是 zip,可直接读)。"""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            info = _read_fabric_mod(zf)
            if info:
                return info
            for cand in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                info = _read_mods_toml(zf, cand)
                if info:
                    return info
    except Exception:
        pass
    return None


def _is_platform(modid: str) -> bool:
    return modid.lower() in _PLATFORM_IDS


def build_graph(mods_dir: str, progress_cb=None) -> ModGraph:
    """扫描 mods_dir 下所有 .jar(含 .jar.disabled),构建依赖图。
    progress_cb(done, total) 可选:每解析一个 jar 回调一次。
    返回 ModGraph。"""
    graph = ModGraph()
    if not os.path.isdir(mods_dir):
        return graph
    files = sorted(f for f in os.listdir(mods_dir)
                   if f.lower().endswith(".jar") or f.lower().endswith(".jar.disabled"))
    total = len(files)
    for i, fname in enumerate(files, 1):
        enabled = not fname.lower().endswith(".disabled")
        meta = read_mod_metadata(os.path.join(mods_dir, fname))
        if meta is None:
            graph.info.append(f"{fname}:未能识别为 mod(jar 元数据读取失败)")
            if progress_cb:
                progress_cb(i, total)
            continue
        node = ModNode(meta["id"], file=fname, name=meta["name"], loader=meta["loader"],
                       version=meta["version"], enabled=enabled)
        graph.add_node(node)
        for tgt, typ, rng in meta["deps"]:
            if _is_platform(tgt):
                continue   # minecraft/fabricloader 等平台依赖,不画进图
            graph.add_edge(meta["id"], tgt, typ, rng)
            graph.ensure_missing(tgt, source_loader=meta["loader"])
        if progress_cb:
            progress_cb(i, total)
    return graph
