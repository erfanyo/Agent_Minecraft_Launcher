"""Copy a launcher-style instance directory without changing its source."""
import json
import os
import shutil
import uuid
from safe_paths import safe_child, safe_component
from instance_metadata import atomic_json


def import_folder(source, game_root):
    from diagnostic_tools import _inventory
    from instance_maintenance import assert_stopped, _lock
    from launcher import resolve_inherited_json
    source = os.path.abspath(source)
    name = safe_component(os.path.basename(source))
    if name.startswith('_'):
        raise ValueError('实例名称不能以下划线开头')
    descriptor = safe_child(source, name + '.json')
    if not os.path.isfile(descriptor):
        raise ValueError('请拖入 versions 下的单个实例文件夹（里面应有同名 JSON），不是整个 .minecraft 或只有 mods 的目录。')
    dest = safe_child(os.path.join(game_root, 'versions'), name)
    source_real, dest_real = os.path.realpath(source), os.path.realpath(dest)
    if os.path.normcase(source_real) == os.path.normcase(dest_real):
        return name  # Already installed: refresh only.
    if os.path.splitdrive(source_real)[0].lower() == os.path.splitdrive(dest_real)[0].lower() and os.path.commonpath([source_real, dest_real]) == source_real:
        raise ValueError('目标位于源文件夹内部，不能递归复制')
    with _lock:
        if os.path.exists(dest):
            raise ValueError('已有同名实例：' + name + '。请先更改源实例名称或选择其他游戏目录，不会覆盖。')
        assert_stopped(source)
        original = _inventory(source)  # Reject links/junctions before copying.
        with open(descriptor, encoding='utf-8') as file:
            detail = json.load(file)
        source_root = os.path.dirname(os.path.dirname(source))
        if detail.get('inheritsFrom'):
            if os.path.basename(os.path.dirname(source)) != 'versions':
                raise ValueError('实例依赖父版本，请从原启动器的 versions 目录拖入，以便读取完整继承信息。')
            detail = resolve_inherited_json(name, source_root)
        source_info = None
        if os.path.basename(os.path.dirname(source)) == 'versions':
            from instances import scan_instances
            source_info = next((v for v in scan_instances(source_root) if v['id'] == name), None)
        stage = safe_child(os.path.join(game_root, 'versions'), '_folder-import-' + uuid.uuid4().hex)
        os.makedirs(os.path.dirname(stage), exist_ok=True)
        shutil.copytree(source, stage)
        if original != _inventory(stage) or original != _inventory(source):
            raise RuntimeError('源文件复制期间发生变化，导入未完成；临时副本保留在：' + stage)
        detail['id'] = name
        detail.pop('inheritsFrom', None)
        def relocate(value):
            if isinstance(value, dict):
                return {k: relocate(v) for k, v in value.items()}
            if isinstance(value, list):
                return [relocate(v) for v in value]
            if isinstance(value, str) and os.path.basename(os.path.dirname(source)) == 'versions':
                return value.replace(source_root, game_root).replace(source_root.replace('\\', '/'), game_root.replace('\\', '/'))
            return value
        detail = relocate(detail)
        if source_info:
            from instance_metadata import read_metadata
            metadata = read_metadata(stage)
            metadata.update(minecraft_version=source_info['base'], loader=source_info['loader'])
            atomic_json(os.path.join(stage, 'amcl_instance.json'), metadata)
        jar = os.path.join(stage, name + '.jar')
        if not os.path.isfile(jar):
            # Do not invent a runnable instance lacking its client core.
            raise ValueError('实例没有同名客户端 JAR，请先在原启动器补全核心。临时副本：' + stage)
        atomic_json(os.path.join(stage, name + '.json'), detail)
        # Copy missing shared resources only; never overwrite another instance's cache.
        if os.path.basename(os.path.dirname(source)) == 'versions' and os.path.realpath(source_root) != os.path.realpath(game_root):
            for directory in ('libraries', 'assets'):
                base = os.path.join(source_root, directory)
                if not os.path.isdir(base):
                    continue
                _inventory(base)
                for root, dirs, files in os.walk(base):
                    for filename in files:
                        relative = os.path.relpath(os.path.join(root, filename), base)
                        output = safe_child(os.path.join(game_root, directory), relative)
                        if not os.path.exists(output):
                            os.makedirs(os.path.dirname(output), exist_ok=True)
                            partial = output + '.import-' + uuid.uuid4().hex
                            with open(os.path.join(root, filename), 'rb') as src, open(partial, 'xb') as dst:
                                shutil.copyfileobj(src, dst)
                            if not os.path.exists(output):
                                os.rename(partial, output)
        if os.path.exists(dest):
            raise ValueError('复制期间出现同名实例，已停止，临时副本：' + stage)
        os.rename(stage, dest)
        return name


def start_import(window, folders):
    from PySide6.QtWidgets import QMessageBox
    from background_tasks import BackgroundTask
    import paths
    if getattr(window, '_folder_import_task', None) and window._folder_import_task.is_running:
        QMessageBox.information(window, '导入实例', '已有文件夹正在导入，请稍等。')
        return
    if QMessageBox.question(window, '导入已有实例',
            '将复制以下实例，保留原文件夹，不覆盖同名实例。请先退出源游戏。\n共享资源也可能占用较多空间。\n' + '\n'.join(folders),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
        return
    root = paths.GAME_DIR
    def work(task):
        results = []
        for folder in folders:
            task.report_status('正在导入：' + os.path.basename(folder))
            try:
                results.append('已导入：' + import_folder(folder, root))
            except Exception as exc:
                results.append(os.path.basename(folder) + '：' + str(exc))
        return '\n'.join(results)
    task = BackgroundTask(work, window)
    window._folder_import_task = task
    task.status.connect(window.statusBar().showMessage)
    def done(result):
        window.refresh_instances()
        QMessageBox.information(window, '导入结果', result)
    task.succeeded.connect(done)
    task.failed.connect(lambda error: QMessageBox.warning(window, '导入失败', error))
    task.start()
