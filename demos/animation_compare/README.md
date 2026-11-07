# Qt Widgets / Qt Quick 动画演示

在项目根目录运行：

也可直接双击本目录的 `run_demo.cmd`。观察标题下方绿色横条的运动是否连续，再试着点击资源卡片。

```powershell
.venv/Scripts/python.exe demos/animation_compare/compare.py
```

左右各一个真实窗口、独立进程，避免 Widgets 的界面线程拖慢另一边。两边均为 120 张资源卡片和同周期整页淡入淡出，可点击卡片检查响应。只使用现有 PySide6，不读取启动器配置，也不连接账号或网络。

依次测试，避免两个窗口争抢资源：

```powershell
.venv/Scripts/python.exe demos/animation_compare/compare.py --benchmark
```

每边运行 12 秒，前 2 秒预热，完成后退出；JSON 报告和窗口截图放在 `.tmp/animation-compare/`。

## 如何看结果

- Widgets 统计透明度效果绘制完成回调；Quick 统计 `frameSwapped` 信号到达界面线程的间隔。后者表示帧已提交到呈现队列，不保证已经显示在屏幕上。两种回调边界不同，不能把比值直接称为速度倍数。
- 同时记录 8 ms 界面定时器的实际间隔，观察界面线程的长停顿。计时结果受系统负载、显示器刷新率、窗口可见性、缩放和 GPU 驱动影响。
- Widgets 使用实时整页透明度基线，**不是已经优化过的 AMCL 页面切换**。QML 采用普通场景图透明度，无额外缓存层。此演示不证明完整启动器迁移后会得到相同收益，也不覆盖网络/磁盘加载卡顿。
- 不启用 offscreen 做帧率结论；软件后端也不能当作 GPU 加速结果。报告记录 Quick 实际图形接口。
- 对比窗口仅说明该场景；实际呈现帧率需要另外使用系统级呈现跟踪工具验证。

## 本机初次结果（2026-10-31）

Qt 6.11.2，240 Hz 显示器，150% 缩放，每边单独运行 7 秒，前 2 秒不计入。

| 指标 | Widgets 整页透明度基线 | Qt Quick（Direct3D 11） |
| --- | ---: | ---: |
| 绘制/帧提交回调频率 | 36.4 次/秒 | 239.6 次/秒 |
| 回调间隔中位数 | 27.17 ms | 4.16 ms |
| 界面定时器间隔 P95（目标 8 ms） | 29.76 ms | 8.84 ms |

回调频率不等同于屏幕实测 FPS，也不能作为完整应用提速倍数。原始报告保存在 `.tmp/animation-compare/benchmark.json`，实时演示报告单独写入 widgets.json / quick.json。

Qt 官方说明：[frameSwapped 信号](https://doc.qt.io/qt-6/qquickwindow.html#frameSwapped)、[Qt Quick 场景图](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)。
