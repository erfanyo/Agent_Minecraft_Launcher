"""Retention for completed UUID-named agent logs, never chat or rollback data."""
import json
import os
from pathlib import Path
import re
import stat
import threading
import time

_NAME = re.compile(r'[0-9a-f]{32}\.jsonl\Z')
_lock = threading.Lock()
_last_cleanup = {}


def _number(settings, key, default, maximum):
    try:
        return max(1, min(maximum, int(settings.get(key, default))))
    except (TypeError, ValueError, OverflowError):
        return default


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _completed(path, info):
    """Read only the tail; malformed/oversized final records are protected."""
    with path.open('rb') as stream:
        stream.seek(max(0, info.st_size - 2 * 1024 * 1024))
        lines = stream.read().rstrip().splitlines()
    if not lines:
        return False
    try:
        row = json.loads(lines[-1])
        return (row.get('schema') == 'amcl.agent-run.v1' and
                row.get('run_id') == path.stem and row.get('event') == 'finish')
    except (ValueError, UnicodeError, AttributeError):
        return False


def cleanup_run_logs(settings, directory, *, now=None, protected=(), dry_run=False):
    """Age first, then oldest-first size pruning. Unfinished records count toward quota.

    In-use, linked, unrecognized and corrupt logs are never deleted. A quota can
    remain exceeded when protected files alone are too large; report that fact.
    """
    days = _number(settings, 'ai_run_log_retention_days', 30, 3650)
    limit = _number(settings, 'ai_run_log_max_mb', 100, 102400) * 1024 * 1024
    cutoff = (time.time() if now is None else now) - days * 86400
    result = dict(deleted=0, freed_bytes=0, remaining_bytes=0, protected=0,
                  failed=0, over_limit=False, dry_run=dry_run)
    root = Path(directory)
    with _lock:
        if not root.exists():
            return result
        if _linked(root.lstat()) or not root.is_dir():
            raise ValueError('运行日志目录不是普通文件夹，未清理。')
        candidates = []
        total = 0
        for path in root.iterdir():
            if not _NAME.fullmatch(path.name):
                continue
            try:
                info = path.lstat()
                if _linked(info) or not stat.S_ISREG(info.st_mode):
                    continue
                total += info.st_size
                if path.stem in protected or not _completed(path, info):
                    result['protected'] += 1
                    continue
                candidates.append((info.st_mtime_ns, path, info))
            except (OSError, ValueError):
                result['failed'] += 1
        for _, path, original in sorted(candidates, key=lambda item: (item[0], item[1].name)):
            if original.st_mtime >= cutoff and total <= limit:
                continue
            try:
                current = path.lstat()
                # Refuse a replaced file or one that changed since inspection.
                if (_linked(current) or current.st_mtime_ns != original.st_mtime_ns or
                        current.st_size != original.st_size or current.st_ino != original.st_ino):
                    result['protected'] += 1
                    continue
                if not dry_run:
                    path.unlink()
                total -= original.st_size
                result['deleted'] += 1
                result['freed_bytes'] += original.st_size
            except OSError:
                result['failed'] += 1
        result['remaining_bytes'] = total
        result['over_limit'] = total > limit
    return result


def auto_cleanup(settings, directory, *, protected=(), force=False):
    if not settings.get('ai_run_log_auto_cleanup', True):
        return None
    key = os.path.abspath(directory)
    now = time.monotonic()
    if not force and now - _last_cleanup.get(key, float('-inf')) < 3600:
        return None
    try:
        result = cleanup_run_logs(settings, directory, protected=protected)
        _last_cleanup[key] = now
        return result
    except (OSError, ValueError):
        # Log maintenance must never interrupt an agent request.
        return None


def cleanup_message(result):
    message = (f"已清理 {result['deleted']} 份运行记录，释放 "
               f"{result['freed_bytes'] / 1024 / 1024:.2f} MB；"
               f"剩余 {result['remaining_bytes'] / 1024 / 1024:.2f} MB。")
    if result['over_limit']:
        message += ' 未结束或受保护的记录仍超出容量上限，已保留。'
    if result['failed']:
        message += f" {result['failed']} 份记录暂时无法处理，可稍后重试。"
    return message
