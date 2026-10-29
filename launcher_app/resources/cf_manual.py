"""Persistent missing-file install state and browser-download handoff."""
import json
import os
import re
import shutil
from pathlib import Path

from launcher_app.core.safe_paths import safe_child, safe_component
from launcher_app.core.task_context import checkpoint

REPORT_NAME = '.amcl-cf-missing.json'


def write_missing_report(instance, failures, files, projects):
    missing = []
    for entry, error in failures:
        file = files.get(entry['fileID'], {})
        project = projects.get(entry['projectID'], {})
        website = (project.get('links') or {}).get('websiteUrl') or f'https://www.curseforge.com/projects/{entry["projectID"]}'
        missing.append({
            'filename': file.get('fileName', ''),
            'folder': {6: 'mods', 12: 'resourcepacks', 6552: 'shaderpacks'}.get(project.get('classId'), ''),
            'sha1': next((h['value'] for h in file.get('hashes', []) if h.get('algo') == 1), ''),
            'url': f'{website.rstrip("/")}/files/{entry["fileID"]}',
            'error': error,
        })
    path = Path(instance, REPORT_NAME)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def receive_downloads(instance, missing, directories):
    """Accept exact bytes only; never move or modify the user's source files."""
    from launcher_app.resources.downloader import sha1_of_file
    remaining = []
    for item in missing:
        checkpoint()
        name, folder, sha1 = item['filename'], item['folder'], item['sha1']
        if not name or folder not in ('mods', 'resourcepacks', 'shaderpacks') or not re.fullmatch(r'[a-fA-F0-9]{40}', sha1):
            remaining.append(item)
            continue
        safe_component(name)
        destination = Path(safe_child(instance, folder + '/' + name))
        candidates = [destination]
        filename = Path(name)
        duplicate = re.compile(re.escape(filename.stem) + r' \(\d+\)' + re.escape(filename.suffix) + '$', re.I)
        for directory in directories:
            candidates.append(Path(directory, name))
            try:
                candidates.extend(Path(entry.path) for entry in os.scandir(directory)
                                  if duplicate.fullmatch(entry.name) and entry.is_file())
            except OSError:
                pass
        found = False
        for source in candidates:
            checkpoint()
            if not source.is_file() or sha1_of_file(str(source)).lower() != sha1.lower():
                continue
            if source != destination:
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + '.amcl-manual-part')
                try:
                    shutil.copyfile(source, temporary)
                    if sha1_of_file(str(temporary)).lower() != sha1.lower():
                        continue
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            found = True
            break
        if not found:
            remaining.append(item)
    return remaining


def show_missing_dialog(parent, error, retry=None):
    match = re.search(r'\[CF_MISSING_REPORT\](.*?)\[/CF_MISSING_REPORT\]', error, re.S)
    if not match:
        return
    from PySide6.QtCore import QStandardPaths, QTimer, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextBrowser, QPushButton, QFileDialog
    from launcher_app.core.background_tasks import BackgroundTask
    path = Path(match.group(1))
    if path.name != REPORT_NAME or not path.is_file():
        return
    missing = json.loads(path.read_text(encoding='utf-8'))
    dialog = QDialog(parent)
    dialog.setWindowTitle('补齐 CurseForge 文件')
    dialog.resize(720, 460)
    layout = QVBoxLayout(dialog)
    label = QLabel('自动下载未成功。点击官方链接下载；会自动校验并复制到实例，原下载文件保留。')
    label.setWordWrap(True)
    layout.addWidget(label)
    listing = QTextBrowser()
    listing.setOpenExternalLinks(True)
    layout.addWidget(listing)
    directories = [QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)]
    open_all = QPushButton('打开全部缺失文件的官方页面')
    choose = QPushButton('选择下载文件夹')
    check = QPushButton('检查并接收下载文件')
    finish = QPushButton('已补齐，继续安装')
    for button in (open_all, choose, check, finish):
        layout.addWidget(button)
    def render():
        from html import escape
        listing.setHtml(f'<p>还缺 {len(missing)} 项</p>' + ''.join(
            f'<p>{escape(item["filename"] or "API 未返回文件名")}<br>'
            f'<a href="{escape(item["url"], quote=True)}">打开官方文件页面</a><br>{escape(item["error"])}</p>' for item in missing))
        finish.setEnabled(not missing)
    active = None
    closing = False
    def received(result):
        nonlocal missing
        if closing:
            return
        missing = result
        render()
        if not missing and retry is not None:
            timer.stop()
            QTimer.singleShot(0, dialog.accept)
    def scan():
        nonlocal active
        if closing or not missing or (active is not None and active.is_running):
            return
        snapshot, folders = list(missing), list(directories)
        active = BackgroundTask(lambda task: receive_downloads(str(path.parent), snapshot, folders), dialog)
        active.succeeded.connect(received)
        active.failed.connect(lambda error: label.setText('接收失败：' + error))
        active.start()
    def choose_folder():
        directory = QFileDialog.getExistingDirectory(dialog, '选择下载文件夹')
        if directory:
            directories.append(directory)
            scan()
    open_all.clicked.connect(lambda: [QDesktopServices.openUrl(QUrl(item['url'])) for item in missing])
    choose.clicked.connect(choose_folder)
    check.clicked.connect(scan)
    finish.clicked.connect(dialog.accept)
    # Polling also catches browsers that replace a temporary file atomically.
    timer = QTimer(dialog)
    timer.setInterval(3000)
    timer.timeout.connect(scan)
    timer.start()
    render()
    QTimer.singleShot(0, scan)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    closing = True
    timer.stop()
    if active is not None and active.is_running:
        active.cancel()
    if accepted and retry:
        QTimer.singleShot(0, retry)
