# 源码目录

业务源码已从根目录迁入 `launcher_app/`，按 AI、浏览器、基础服务、扩展、实例、资源、
运行组件、服务端、界面分包；`features/` 放随本体发布的正式功能。使用标准 Python 包导入，例如：

```python
from launcher_app.ai.assistant import build_executor
from launcher_app.resources.downloader import download_file
from launcher_app.runtime.java_manager import list_java_installations
```

根目录保留 `main.py`、`cli.py`、`ci_smoke.py`、`paths.py`，以及构建配置和依赖清单。
`settings/` 与 `os_platform/` 保持已有包路径。`plugins/` 是可加载插件，
`launcher_app/extensions/` 是启动器自身的插件支持代码。
联机与辅助资源等正式功能已迁入本体，详见 [本体功能说明](builtin-features.md)。

`AMCL/` 仍是用户数据和下载运行组件目录；`launcher_app/` 是源码，两者不能互相替代。
游戏数据、模型、账号配置、历史成品的位置不因源码整理而变化。

## 常用命令

在项目根目录运行：

```text
python main.py
python cli.py --help
python ci_smoke.py
python -m unittest discover -v
python -m pytest tests/unit
python -m pytest tests/ui
python -m launcher_app.ui.ui_color_scan
python -m launcher_app.ui.ui_bench
python -m launcher_app.ai.dev_model_server
```

原根目录测试和原 `tests/test_*.py` 已统一放入 `tests/unit/`，测试文件名保留。
单个测试可使用 `python -m unittest tests.unit.test_ai_run` 或
`python -m pytest tests/unit/test_browser_setup.py`。

两个 PyInstaller 配置与 CI 检查的动态模块名均使用完整包名。
源码中启动辅助进程经根目录入口分派，资源路径仍指向项目或打包资源根目录。
修改内部导入的第三方插件需要改用完整包名；公开的 `register(api)` 插件入口保持原样。

AI 原始运行日志的自动保留与清理规则见 [运行日志回收](run-log-retention.md)。
