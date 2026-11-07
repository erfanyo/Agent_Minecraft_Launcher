"""Shared loader and optional-component catalog for UI, CLI and AI installation."""

SHADER_MODS = {"fabric": "iris", "forge": "oculus", "neoforge": "iris"}

OPTIMIZE_MODS = {
    "fabric": ["sodium", "lithium", "ferrite-core"],
    "forge": ["embeddium", "ferrite-core"],
    "neoforge": ["sodium", "lithium", "ferrite-core"],
}

LOADER_CHOICES = [
    ("原版(无加载器)", None, None),
    ("Fabric", "fabric", "fabric"),
    ("Quilt", "quilt", "quilt"),
    ("Forge", "forge", "forge"),
    ("NeoForge", "neoforge", "neoforge"),
]
