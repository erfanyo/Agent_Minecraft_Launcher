# -*- coding: utf-8 -*-
"""
os_platform 包:把散落在项目各处的【平台相关代码】抽象到这里,便于跨平台(Windows/macOS/Linux)。

**为什么叫 os_platform**:Python 已有标准库 `platform`,`platform/` 包名会遮蔽它,
导致其它文件(如 game_files.py/lan_tools.py 的 `import platform`)出错。
用 `os_platform` 规避冲突。

**为什么要抽象**:之前平台判断(`sys.platform == "win32"`)、Windows 专用的 `os.startfile`/
WMI 读取、无边框窗口补丁等散落在 main.py / assistant.py / instance_manager.py 里,
macOS/Linux 上会崩或退化。统一收口到本包后:
- 新平台只需改这里一处;
- 各消耗方(主窗口/温度检测/打开目录/通知)调用统一接口,不关心底层平台。

模块:
- system.py      OS/架构检测(is_windows/is_macos/is_linux/current_os_name/current_arch)
- openpath.py    跨平台打开文件/文件夹(替换 os.startfile)→ Windows startfile / mac open / Linux xdg-open
- temperature.py CPU 温度可插拔(Windows WMI/psutil、Linux sensors、macOS powermetrics)
- notify.py      系统通知(托盘弹窗;Qt 不可用时降级为无操作)
"""
