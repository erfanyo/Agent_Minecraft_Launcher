# -*- coding: utf-8 -*-
"""路径常量:整个项目共用的游戏目录位置。"""
import os

# 游戏目录:启动器同目录下的 .minecraft(已在 .gitignore 里排除)
GAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".minecraft")
# 自带 Java 运行时目录(自动下载的 JRE 放这里)
RUNTIME_DIR = os.path.join(GAME_DIR, "runtime")
