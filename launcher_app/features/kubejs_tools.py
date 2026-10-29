# -*- coding: utf-8 -*-
'本体 KubeJS 工具：只读浏览脚本，定位客户端与服务端报错。'
FEATURE_ID = "kubejs_tools"
FEATURE_NAME = "KubeJS 工具"
FEATURE_DESCRIPTION = ("浏览 KubeJS 脚本并定位报错(只读)。"
                      "脚本报错会让服务端直接启动失败,这里可以跳到出错的那一行。")
FEATURE_VERSION = "1.0.0"
FEATURE_API_VERSION = 1

#: KubeJS 自身的 mod id 就是 kubejs。
WATCH_MODS = ("kubejs",)

from launcher_app.core.i18n import t
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)


def register(api):
    def build_tab():
        from launcher_app.instances.kubejs_targets import all_targets, find_target, label_for, target_key
        from launcher_app.ui.kubejs_viewer import KubejsViewer
        from paths import GAME_DIR

        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        row.addWidget(QLabel(t('选择实例/服务端：')))
        combo = QComboBox()
        combo.setMinimumWidth(260)
        refresh_btn = QPushButton(t('重新扫描'))
        row.addWidget(combo, 1)
        row.addWidget(refresh_btn)
        layout.addLayout(row)

        holder = QVBoxLayout()
        layout.addLayout(holder, 1)

        state = {'viewer': None, 'targets': []}

        def clear_viewer():
            viewer = state['viewer']
            if viewer is not None:
                holder.removeWidget(viewer)
                viewer.setParent(None)
                viewer.deleteLater()
                state['viewer'] = None

        def open_target(target):
            clear_viewer()
            if target is None:
                return
            viewer = KubejsViewer(target['kubejs'])
            state['viewer'] = viewer
            holder.addWidget(viewer, 1)
            # 记住选择:下次打开直接回到同一个目标
            api.set_config('last_target', target_key(target))
            # 顺带把日志里的 KubeJS 报错喂进去(有服务端就看服务端的)
            viewer.set_log(_collect_log(target))

        def reload_targets():
            targets = all_targets(GAME_DIR)
            state['targets'] = targets
            combo.blockSignals(True)
            combo.clear()
            if not targets:
                combo.addItem(t('（没有找到带 kubejs 目录的实例或服务端）'), None)
            else:
                for target in targets:
                    combo.addItem(label_for(target), target_key(target))
                last = api.get_config('last_target', '')
                index = combo.findData(last)
                combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
            combo.setEnabled(bool(targets))
            if targets:
                open_target(find_target(targets, combo.currentData()))
            else:
                clear_viewer()

        def on_changed(_index):
            open_target(find_target(state['targets'], combo.currentData()))

        combo.currentIndexChanged.connect(on_changed)
        refresh_btn.clicked.connect(reload_targets)
        reload_targets()
        return page

    api.register_main_tab(label=FEATURE_NAME, build_fn=build_tab)


def _collect_log(target) -> str:
    """尽量收集与目标相关的日志,供报错定位使用。

    客户端实例没有服务端那样的托管日志,退回读实例目录下的 logs;
    服务端读它的托管运行日志(最近几个)与 logs/latest.log。
    """
    import os

    root = os.path.dirname(target.get('kubejs') or '')
    chunks = []

    def tail(path, lines=1200):
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, encoding='utf-8', errors='replace') as stream:
                content = stream.read().splitlines()
        except OSError:
            return
        chunks.append('\n'.join(content[-lines:]))

    if target.get('kind') == 'server':
        runtime = os.path.join(root, '.amcl-runtime', 'logs')
        if os.path.isdir(runtime):
            try:
                files = [os.path.join(runtime, name)
                         for name in os.listdir(runtime) if name.endswith('.log')]
            except OSError:
                files = []
            files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            for path in files[:3]:
                tail(path)
    tail(os.path.join(root, 'logs', 'latest.log'))
    tail(os.path.join(root, 'logs', 'kubejs', 'server.log'))
    return '\n'.join(chunks)
