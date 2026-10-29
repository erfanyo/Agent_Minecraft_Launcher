"""Clean up only server staging directories created by this operation."""
from contextlib import contextmanager
import logging
from pathlib import Path
import shutil
import tempfile
import time


@contextmanager
def server_staging_directory(*, prefix, dir, status=lambda _: None):
    parent = Path(dir).resolve(strict=True)
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    original_error = None
    try:
        yield str(folder)
    except BaseException as error:
        original_error = error
        raise
    finally:
        cleanup_error = None
        for attempt in range(12):
            try:
                if not folder.exists():
                    cleanup_error = None
                    break
                # Recheck on every attempt: never follow a replaced staging link.
                if (folder.is_symlink() or folder.is_junction()
                        or folder.resolve().parent != parent
                        or not folder.name.startswith(prefix)):
                    raise ValueError('临时目录位置发生变化，已停止清理。')
                shutil.rmtree(folder)
                cleanup_error = None
                break
            except OSError as error:
                cleanup_error = error
                if getattr(error, 'winerror', None) not in (5, 32, 145) and not isinstance(error, PermissionError):
                    break
                if attempt < 11:
                    time.sleep(.25)
            except ValueError as error:
                cleanup_error = error
                break
        if cleanup_error is not None:
            message = f'临时目录清理未完成，已保留：{folder}（{cleanup_error}）'
            logging.getLogger(__name__).warning(message)
            if original_error is not None:
                original_error.add_note(message)
            else:
                # The prepared server / ZIP is valid even if Windows still holds
                # a staging directory. Do not turn successful export into failure.
                try:
                    status(message)
                except Exception:
                    pass
