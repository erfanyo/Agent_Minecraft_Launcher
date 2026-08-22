# -*- coding: utf-8 -*-
"""
AI 助手的文件操作权限:只读 / 工作区可写 两档。

以后 AI 执行任何动作(改设置、写配置、装 Mod)都必须先过这里的检查:
- 只读(readonly)        → 一切写操作直接拒绝
- 工作区可写(workspace_write) → 只能碰项目工作区内的路径,工作区之外一律拒绝

这是"权限边界"的实现:即使 AI 想越权,代码层也会拦下来。
"""
import os

WORKSPACE = os.path.dirname(os.path.abspath(__file__))  # 项目根目录(工作区)

# 两档权限(界面选项:显示名, 内部值)
PERMISSIONS = [
    ("只读(不能修改任何文件)", "readonly"),
    ("工作区可写(可改启动器目录内文件)", "workspace_write"),
]


class PermissionDenied(PermissionError):
    """AI 越权被拒绝"""
    pass


def permission_allows_write(settings: dict) -> bool:
    """当前 AI 是否允许写操作"""
    return settings.get("ai_permission", "readonly") == "workspace_write"


def permission_instructions(settings: dict) -> str:
    """告诉 AI 它的权限边界(作为系统提示的一部分)"""
    if permission_allows_write(settings):
        return ("你的文件权限:工作区可写。你可以修改启动器工作区内的文件,"
                "但绝不能碰工作区之外。任何改动前先说明你的计划。")
    return "你的文件权限:只读。你只能阅读和分析,绝不能修改、删除或创建任何文件。"


def is_within_workspace(path: str) -> bool:
    """路径是否在工作区内"""
    abs_path = os.path.abspath(path)
    return abs_path == WORKSPACE or abs_path.startswith(WORKSPACE + os.sep)


def require_workspace_write(settings: dict) -> None:
    """写操作前调用:没有工作区写权限直接拒绝"""
    if not permission_allows_write(settings):
        raise PermissionDenied(
            "AI 当前是只读权限,不能修改文件(可在 AI 设置中改为\"工作区可写\")")


def safe_write_path(settings: dict, path: str) -> str:
    """返回经过校验的写入路径:先查写权限,再查路径必须在工作区内"""
    require_workspace_write(settings)
    abs_path = os.path.abspath(path)
    if not is_within_workspace(abs_path):
        raise PermissionDenied(f"写入路径在工作区之外,已拒绝:{abs_path}")
    return abs_path
