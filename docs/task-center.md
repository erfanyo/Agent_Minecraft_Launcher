# 状态球与统一任务呈现接口

状态球是任务与日志入口。`task_center.py` 负责呈现，原下载协调器、后台任务和服务端控制器负责实际执行，不把工作搬到 UI 线程。

## 交互约定

- 点击状态球展开非模态任务浮窗，每个任务一个标签。收起只隐藏界面，取消是独立操作。
- 服务端导出从准备、隔离测试到打包沿用同一任务 ID 和详情页。内部轮次不新增标签。
- 多任务只显示活动数量与旋转动画，百分比在各自详情页显示。未知总量使用忙碌动画，不生成假的完成比例。
- 待确认时球展开为可拖动卡片，问题排队。明确点击操作按钮才回答；不默认触发 Enter，不调用 activateWindow，不强制置顶。
- 卡片可收起，问题仍待确认；点击回启动器也收起卡片，避免卡片被压到窗口后失去入口。再次点击状态球恢复。
- 拖动通过标题区域，优先 Qt 原生系统拖动（含 Wayland），不支持时使用手动移动。位置在本次运行内保留，展示时限制到屏幕可用区域。
- 初次展开有短几何动画，遵守全局动画开关。Minecraft EULA 仍使用完整协议阅读界面，不简化成普通是否卡片。

## API（稳定入口）

通过 `task_center_for(widget)` 获取当前启动器的任务中心；无主窗口时返回 `None`，组件保持原有独立使用方式。

```python
from task_center import task_center_for

hub = task_center_for(self)
task_id = hub.begin_task('任务名', cancel=worker.cancel)
hub.attach_background(worker, task_id)
worker.start()
```

- `begin_task(title, task_id=None, page=None, cancel=None)`：返回任务 ID。显式 ID 可复用任务；page 为专用详情 QWidget，未指定时提供状态、进度、日志和取消按钮。
- `register_page(task_id, page)`：替换专用详情页；页面由任务中心托管。
- `update_task(task_id, message=None, done=None, total=None, state=None)`：主线程更新。状态为 `idle/running/completed/failed/cancelled`，等待确认由队列派生。
- `report(task_id, **fields)`：工作线程安全地提交上述状态字段，经 Qt 信号返回 UI 线程。
- `finish_task(task_id, state='completed', message=None)`：明确终态。大任务中的一个准备步骤完成不等于整个任务完成。
- `attach_background(worker, task_id, finish=True)`：绑定 `BackgroundTask`；多阶段工作流传 `finish=False`，由控制器最终调用 finish_task。失败、取消仍立即记录。
- `request_confirmation(task_id, title, question, choices, callback)`：异步排队。choices 是 `(按钮文案, 返回值)` 列表；取消等待或应用退出时回调 `None`，不能继续启动后续工作。
- `cancel_confirmation(task_id)`：撤销该任务的待确认问题，回调 None。
- `show_task(task_id)`：展开详情并选择对应标签。

旧 GUI 同步 Yes/No 调用通过 `task_question` 兼容，用局部 Qt 事件循环等待回答，其他窗口保持响应；新功能应优先使用异步 callback。不要在工作线程调用 task_question。

## 当前接入范围

- 下载与游戏启动准备：复用现有日志、取消、重试和启动器日志，状态球不再覆盖主内容。
- 服务端导出：专用页面嵌入任务标签；测试选择使用异步确认；轮数、停用 Mod、实际复制/压缩进度保留。
- 服务端后台管理：工作步骤接入统一状态、进度、错误和取消，Yes/No 问题使用确认卡片。
- 其他功能与插件可使用上述接口接入；尚未把所有历史 QMessageBox 和独立导出窗口全部迁移。禁止全局替换 QMessageBox，避免误改有专门交互要求的窗口。

已接入 `tests/ui` 的 pytest-qt 自动化交互、深浅主题截图与普通/150% DPI 场景，详见 `docs/ui-testing.md`。Windows 离屏结果通过；原生桌面焦点、Wayland 拖动和服务端真实导出整条流程仍需桌面验收。
