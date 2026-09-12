"""Cheap catalog change detection; excludes launcher-generated catalog output."""
import os


def fingerprint(root):
    rows = []
    versions = os.path.join(root, 'versions')
    try:
        with os.scandir(versions) as entries:
            for entry in entries:
                if entry.name.startswith('_') or not entry.is_dir():
                    continue
                for path in (os.path.join(entry.path, entry.name + '.json'),
                             os.path.join(entry.path, 'amcl_instance.json'),
                             os.path.join(versions, '_imports', entry.name + '.json')):
                    try:
                        stat = os.stat(path)
                        rows.append((path, stat.st_mtime_ns, stat.st_size))
                    except OSError:
                        rows.append((path, None, None))
    except OSError:
        pass
    return (os.path.normcase(os.path.abspath(root)), tuple(sorted(rows)))
