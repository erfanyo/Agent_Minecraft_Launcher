"""Permanent original modpack downloads, isolated per download attempt."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def new_download_directory(game_dir):
    from paths import safe_child
    # Separate requests cannot overwrite each other's identically named archives.
    relative = 'downloads/modpacks/' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:12]
    directory = Path(safe_child(game_dir, relative))
    directory.mkdir(parents=True, exist_ok=False)
    return str(directory)
