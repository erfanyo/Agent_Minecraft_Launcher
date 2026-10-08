# 长列表：限长 + 搜索框（做法记录）

> 以后发现有列表太长，照本文加即可。**约定：所有长列表限高；条目超过 20 个才在顶部显示搜索框。**

## 一、约定

| 项 | 值 | 说明 |
|---|---|---|
| 出现搜索框的阈值 | **> 20 条** | 不够长就不占地方，避免到处是搜索框 |
| 列表限高 | **200–260 px** | 列表再长也不把界面撑爆；配滚动条 |
| 过滤方式 | **隐藏条目** | 不删除条目，选中项 / 绑定数据语义不变 |

阈值和默认高度定义在 [`list_search.py`](../list_search.py)：`DEFAULT_THRESHOLD = 20`、`DEFAULT_MAX_HEIGHT = 260`。

## 二、已应用的位置

| 位置 | 控件 | 做法 |
|---|---|---|
| 模型目录（设置 → 模型 → 服务商卡片） | 自定义行（`QVBoxLayout` + `ModelRow`） | [`model_cards.py`](../model_cards.py) `_build_api`：`QScrollArea` 限高 200 + 搜索框 + `setVisible` 过滤 |
| 资源文件版本（资源中心 → 详情面板） | `QComboBox` | [`resource_center.py`](../resource_center.py) `_render_versions`：搜索框 + 用全集重填下拉 |

## 三、三种情形怎么做

### 情形 A：`QListWidget` / `QTreeWidget`（最省事，一行）

```python
from list_search import make_searchable

make_searchable(self.some_list)                 # 默认 >20 条出现搜索框、限高 260
make_searchable(self.some_list, max_height=200) # 想更矮
```

`make_searchable` 会自动：

1. 在**原控件所在的布局位置**插入「搜索框 + 列表」的容器（不用改布局代码）；
2. 给列表限高；
3. 连接列表模型的 `rowsInserted / rowsRemoved / modelReset / layoutChanged`，
   之后**内容增删会自动决定搜索框显隐**、并重新套用过滤词。

想手动控制时，返回的句柄可用：

```python
handle = make_searchable(self.some_list)
handle.refresh()          # 内容变了手动刷新
handle.apply()            # 只重新套用当前搜索词
handle.edit.text()        # 当前搜索词
```

### 情形 B：自定义行（`QVBoxLayout` 里一堆 widget，如模型目录）

`make_searchable` 不适用（不是列表控件），照 [`model_cards.py`](../model_cards.py) 的 `_build_api` 抄：

1. 行容器：`self.rows_box = QVBoxLayout()`，外面套：
   ```python
   host = QWidget(); host.setLayout(self.rows_box)
   scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(host)
   scroll.setMaximumHeight(200)                      # ← 限长
   scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
   scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                        "QScrollArea > QWidget > QWidget { background: transparent; }")
   ```
2. 搜索框：`QLineEdit` + `textChanged → 过滤函数`，初始 `setVisible(False)`。
3. 过滤函数按搜索词 `row.setVisible(匹配)`。
4. **增删行的函数里统一调一个 `_after_rows_changed()`**：更新计数、`搜索框.setVisible(len(rows) > 20)`、重新套用过滤。

### 情形 C：`QComboBox`（如资源版本）

下拉不能"隐藏条目后又保住 `currentData()`"，所以按 [`resource_center.py`](../resource_center.py) 的做法：

1. 搜索框放在下拉**上方**（`mp.addWidget(self.version_search)`，在版本那一行之前）。
2. 把「填下拉」拆成两个方法：
   - `_fill_versions(versions)`：只**保存全集** `self._loaded_versions = list(versions)`，然后转调下一个；
   - `_render_versions()`：`setVisible(len(全集) > 20)` → 按搜索词过滤全集 → **重填** `clear()` + `addItem(...)`。
3. 下拉本身的限高用 `setMaxVisibleItems(8)` + `setView(QListView(...))`（Windows 原生弹层会忽略该设置）。
4. **要点**：重填的每一项仍是**真实数据对象**，所以 `currentData()` 语义不变，下载逻辑无需改。

## 四、加到一个新列表时的检查清单

- [ ] 列表是否限高（`setMaximumHeight`）？滚动条是否可用？
- [ ] 搜索框是否 `> 20` 条才显示、少了自动隐藏？
- [ ] 过滤后**选中项 / `currentData()` 是否仍有效**？（尤其 `QComboBox`）
- [ ] 内容增删后搜索框显隐会不会自动更新？（情形 A 自动；B/C 需在新数据入口调用刷新）
- [ ] 暗色 / 亮色主题下搜索框颜色正常吗？（用 `text_color()` / `muted_color()`，别写死颜色）

## 五、怎么验证

纯界面逻辑，用离屏冒烟最快（不用真开启动器）：

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

lst = QListWidget()
for i in range(30):
    lst.addItem(f"item-{i:03d}")
host = QWidget(); lay = QVBoxLayout(host); lay.addWidget(lst)   # 必须保住 host 引用
handle = make_searchable(lst)
assert not handle.edit.isHidden()          # >20 → 搜索框可见
handle.edit.setText("item-00")
# 断言只剩余匹配项可见
```

> ⚠️ **坑**：宿主 widget 一定要留引用（局部变量 / `self.`）。否则 Python 先 GC 掉它，
> 底层 C++ 对象随之销毁，后续访问会报 `libshiboken: Internal C++ object already deleted`。

`list_search.py` 自身有回归测试：[`test_list_search.py`](../test_list_search.py)
（阈值显隐、过滤、限高、条目增长后自动出现、`QTreeWidget` 支持、非列表控件报错）。

跑法：

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.venv\Scripts\python.exe -m unittest test_list_search -v
```

## 六、已知的 Windows 权限坑（与列表无关，但会挡住改文件）

本机的 `docs\`、`assets\`、`tmp\` 三个目录**沙箱子进程无法写入/删除**（新建文件、建子目录、`del` 都被拒），
而项目根、`benchmark\`、以及**新建目录**都正常。

- 图片等二进制资源因此放在新目录 `docs-assets\`；
- 若 `tmp\` 里的临时脚本删不掉，请手动清理，或把会话切到「完全权限」。
