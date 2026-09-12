# 插件界面扩展

新增接口向后兼容 API 1。需要更新一次启动器才能使用；插件可通过
`hasattr(api, 'register_center_page')` / `hasattr(api, 'open_web_window')` 检测支持。

## 中心侧栏页面

```python
api.register_center_page('online', 'my_page', '我的联机工具', build_page)
```

目前 center 支持 `online`（联机中心）。`build_page()` 在首次进入时于 GUI
线程调用，返回 QWidget。启动器提供滚动容器。只有已启用且成功注册的插件应提供
页面；新增注册在重启后生效。同一插件的 page_id 不可重复，插件页面标题不能重复。
已有 `register_main_tab` 用于主导航；`register_settings_page` 用于设置页。
EasyTier 现在通过公开接口注册，不再由联机中心硬编码构建其设置页。

## 独立网页窗口

```python
def open_editor():  # 从按钮点击等 GUI 线程入口调用
    window = api.open_web_window(
        '原理图预览',
        '''<h1>预览示例</h1><button onclick="load()">读取摘要</button>
        <pre id="result"></pre><script>
        async function load() {
          const reply = await window.amcl.call('summary', null);
          document.querySelector('#result').textContent = JSON.stringify(reply);
        }
        </script>''',
        handlers={'summary': lambda payload: {'blocks': 100}},
        width=1100, height=760,
    )
    # 如需主动关闭，保留 window 并调用 window.close()。
```

交互需等待 `pywebviewready` 事件后使用（用户点击时也要确认组件已就绪）。
`window.amcl.call(name, payload)` 返回 Promise，结果为
`{ok: true, result: ...}` 或 `{ok: false, error: ...}`。
参数和返回值必须能 JSON 序列化；每条消息上限 8 MiB（JSON 转义后）。
回调在启动器 GUI 线程执行，必须短小；大型原理图解析需插件自行放入后台任务，
通过任务 ID 查询进度，不应在回调里长时间阻塞。窗口进程独立，不提供任意 Python
执行、任意文件读取或自动保存接口；文件选择、备份、保存确认由插件明确实现。
这不是不可信 Python 插件的硬沙箱，HTML 与回调也应来自可信插件。

仅接收内联 HTML，CSS/JS 需内联，图片可用 data/blob。默认禁止网络请求、iframe、
表单提交和 file URL，不支持随意打开远程网页；不要把不可信内容作为 HTML 拼接。
交互密钥仅注入初始页面，导航到其他页面不能继续调用宿主方法。
用户关闭窗口会询问确认；宿主 close() 或启动器退出会强制结束窗口，插件需自行
设计草稿保存。错误默认弹窗，可通过 `on_error(message)` 自定义提示。

## 依赖与发布

开发环境：`pip install -r requirements-webview.txt`。这是可选能力，不安装不会影响
启动器其他功能。Windows 强制使用系统 WebView2，缺失时提示，不自动安装；macOS
使用 Cocoa/WebKit；Linux 使用 GTK/WebKit（系统依赖需另装）。不回退到 QtWebEngine。
网页宿主按需启动，不在启动器启动时导入 pywebview。

项目 spec 在安装 pywebview 的构建环境收集宿主依赖，排除 QtWebEngine/CEF；
仍须验证实际打包产物，尤其是 pythonnet/.NET 桥接依赖。没有安装 pywebview 的构建
仍能运行启动器，但网页窗口会提示缺少组件。并未实现多文件插件压缩包安装，
此接口也不等于原理图解析/编辑器本身。
