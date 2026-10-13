# Qt UI 测试

## 分层

1. 现有 unittest 覆盖业务逻辑、下载/安装安全与进程生命周期，不强行迁移。
2. `tests/ui` 使用 pytest-qt 的真实 Qt 控件，模拟任务结果和进度，不下载资源、不运行游戏、不修改真实设置。
3. 固定视觉场景保存 PNG，失败时另保存可见窗口和任务状态。原生窗口行为仍需 Windows / Wayland 桌面验收。

## 本地运行

先在已有项目虚拟环境安装测试依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.venv\Scripts\python.exe -m pytest tests/ui -q
```

只运行指定交互：

```powershell
.venv\Scripts\python.exe -m pytest tests/ui -k "confirmation" -q
```

模拟 150% 缩放建议另开终端运行，避免环境变量影响其他 GUI：

```powershell
$env:QT_SCALE_FACTOR = '1.5'
.venv\Scripts\python.exe -m pytest tests/ui --ui-artifacts=.tmp/ui-test-artifacts-highdpi
```

默认离屏平台由 conftest 设置。已有实际桌面时可显式设置 `QT_QPA_PLATFORM=windows` 或 Linux `xcb/wayland`，但模拟拖动用例仅验证手动回退，不能代替原生 Wayland 拖动验证。

## 测试约定

- 控件使用稳定 `objectName`，避免根据中文文案或像素坐标定位普通按钮。
- 普通控件直接调用 `click()/setText()/setCurrentIndex()`，拖动等自定义行为使用 qtbot 鼠标事件。
- 使用 `qtbot.waitSignal/waitUntil` 等待条件，不用固定 sleep 猜加载时间。
- 多数用例注入“准备完成/失败/进度”；整合包用例另在临时目录实际导出少量文件，不访问真实实例。
- 动画默认关闭以保证确定性；后续动画测试应单独开启，并等待动画结束信号。
- 每个用例恢复主题、字体和任务中心，释放窗口及应用级事件过滤器，避免测试之间互相污染。
- 进度计数使用 Python 整数的 Qt object 信号，覆盖大于 2 GiB 的值。

## 当前样板

52 项覆盖多任务独立进度、确认排队、连续确认、无默认 Enter 提交、收起恢复与渐隐、关闭标签与重新打开、取消、退出、失败重试、跨线程状态、拖动、屏幕限制、长提示滚动、深浅主题、提示分流与原生弹窗回退，以及服务端导出流程和 ZIP / CurseForge / Modrinth 后台导出。

`test_visual_scenes.py` 每轮生成 8 张图（两种主题 × 多任务/确认/失败/就地提示），位于 `.tmp/ui-test-artifacts/scenes/`。离屏测试会从系统加载中文字体，仅作用于测试进程，不复制字体到仓库或发布包。

失败产物：

- `.tmp/ui-test-artifacts/<测试名>/`：可见窗口 PNG 和 `state.json`。
- `--junitxml=.tmp/ui-test-results.xml`：结构化结果。
- `--ui-artifacts=<目录>`：指定产物目录。

截图目前供人工对照，**没有自动像素基线比较**；不同系统字体、DPI 和 Qt 版本的图片不能直接混作同一基线。后续可在固定系统/DPI上建立基线，再逐页扩展资源详情、设置、登录、联机等场景。

CI 在 Windows / Linux / macOS 测试作业中执行现有 unittest、普通 DPI UI 用例、150% DPI UI 用例，并上传 JUnit、场景截图及失败截图。本地通过不代表远端三平台已经通过，需推送后查看实际 run。
