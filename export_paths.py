"""Small path helpers shared by export UIs and headless code."""
from pathlib import Path
import re


def compose_zip_destination(directory, filename):
    directory = str(directory or '').strip()
    filename = str(filename or '').strip()
    if not directory:
        raise ValueError('请选择保存目录。')
    if not filename:
        raise ValueError('请填写文件名。')
    if Path(filename).name != filename or filename in ('.', '..'):
        raise ValueError('文件名不能包含路径或目录分隔符。')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename) or filename.rstrip(' .') != filename:
        raise ValueError('文件名包含 Windows 不允许的字符，或以空格/句点结尾。')
    if not filename.lower().endswith('.zip'):
        filename += '.zip'
    return str(Path(directory).expanduser().absolute() / filename)

