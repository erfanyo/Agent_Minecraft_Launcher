"""Online mod compatibility and installation, independent of the UI."""
# ================= 联机 Mod 一键配置(Essential / e4mc) =================
# 给"一键配置"提供判断"某实例版本+加载器是否支持某联机 mod",以及下载安装。
# 判断用 Modrinth get_project 的 game_versions × loaders 精确匹配(不放宽),
# 和 get_mod_version(会逐级放宽)不同 —— 这里要的是"该版本到底有没有这个 mod"。

# 可一键配置的联机 mod:slug → 显示名(装到实例 mods/ 下)
ONLINE_MODS = {
    "essential": "Essential(联机 mod)",
    "e4mc": "e4mc(局域网联机 mod)",
}


def mod_supported(slug: str, game_version: str, loader: str) -> bool:
    """判断某联机 mod 是否支持"指定 MC 版本 + 加载器"。精确匹配(game_versions×loaders)。

    game_version/loader 为空时按"不指定"处理(全支持)。网络失败时保守返回 False
    (宁可不显示,不让用户装到不兼容的版本)。"""
    if not slug:
        return False
    try:
        from launcher_app.resources.modrinth import get_project
        p = get_project(slug)
        gvs = p.get("game_versions", [])
        lds = p.get("loaders", [])
        # 加载器:实例 loader fabric/forge/neoforge 直接匹配;Modrinth 里可能有 quilt 等,忽略
        if loader and (lds and loader not in lds):
            return False
        if game_version and (not gvs or game_version not in gvs):
            return False
        # 都在 → 基本可用(还差"该版本+加载器是否有具体文件",交给下载时 get_mod_version 兜底)
        return True
    except Exception:
        return False


def online_mod_supported_map(game_version: str, loader: str) -> dict:
    """返回 {slug: bool}:哪些联机 mod 支持该实例版本+加载器(供菜单动态显隐)。"""
    out = {}
    for slug in ONLINE_MODS:
        out[slug] = mod_supported(slug, game_version, loader)
    return out


def install_online_mod(slug: str, game_version: str, loader: str,
                       mods_dir: str, progress_callback=None) -> str:
    """下载并安装某联机 mod 到实例 mods 目录。返回状态文本(成功含文件名)。
    失败返回原因文本。"""
    from launcher_app.resources.modrinth import download_mod, get_mod_version
    try:
        # 严格先确认版本支持(避免装到不兼容)
        if not mod_supported(slug, game_version, loader):
            return f"{ONLINE_MODS.get(slug, slug)} 不支持 {game_version}+{loader}"
        fn = download_mod(slug, game_version, loader, mods_dir,
                          progress_callback=progress_callback)
        if not fn:
            return f"没有 {game_version}+{loader} 的可用版本({ONLINE_MODS.get(slug, slug)})"
        return f"已安装 {ONLINE_MODS.get(slug, slug)}:{fn}"
    except Exception as e:
        return f"安装失败:{type(e).__name__}: {e}"
