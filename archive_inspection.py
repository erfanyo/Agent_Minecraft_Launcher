#!/usr/bin/env python3

import hashlib
import json
import re
import stat
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

STAGING = Path("/opt/minecraft/staging").resolve()
MAX_ARCHIVE = 8 * 1024**3
MAX_EXPANDED = 16 * 1024**3
MAX_SINGLE_FILE = 4 * 1024**3
MAX_FILES = 100_000


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(path: Path, progress_callback=None) -> str:
    digest = hashlib.sha256()
    done = 0
    total = path.stat().st_size
    last_report = 0.0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            done += len(chunk)
            if progress_callback and time.monotonic() - last_report >= 0.2:
                progress_callback(done, total)
                last_report = time.monotonic()
    if progress_callback:
        progress_callback(done, total)
    return digest.hexdigest()


def normalize_member(name: str) -> str:
    name = name.replace("\\", "/")
    for part in name.rstrip('/').split('/'):
        if (not part or part in ('.', '..') or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in ':*?"<>|' for c in part)
                or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part)):
            fail(f"unsafe ZIP path: {name}")

    if "\x00" in name:
        fail("ZIP contains a NUL byte in a path")

    path = PurePosixPath(name)

    if path.is_absolute() or ".." in path.parts:
        fail(f"unsafe ZIP path: {name}")

    if path.parts and re.match(r"^[A-Za-z]:$", path.parts[0]):
        fail(f"Windows absolute ZIP path: {name}")

    normalized = "/".join(
        part for part in path.parts
        if part not in ("", ".")
    )

    if not normalized:
        fail("ZIP contains an empty path")

    return normalized


def parse_version(value: str) -> tuple[int, ...]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        return ()
    return tuple(
        int(part) if part is not None else 0
        for part in match.groups()
    )


def required_java(mc_version: str | None) -> int | None:
    if not mc_version:
        return None

    version = parse_version(mc_version)

    if version >= (1, 20, 5):
        return 21
    if version >= (1, 18, 0):
        return 17
    if version >= (1, 17, 0):
        return 16
    return 8


def inspect_archive(path, *, max_files=50_000,
                    max_expanded_bytes=MAX_EXPANDED,
                    max_single_file_bytes=MAX_SINGLE_FILE,
                    status_callback=None, progress_callback=None):
    """Scan without extracting or executing. Raises ValueError on unsafe archives."""
    archive = Path(path).resolve(strict=True)

    if not archive.is_file():
        fail("archive is not a regular file")

    if archive.suffix.casefold() not in (".zip", ".mrpack"):
        fail("only .zip / .mrpack archives are accepted")

    archive_size = archive.stat().st_size
    if archive_size > MAX_ARCHIVE:
        fail("compressed archive exceeds 8 GiB")

    try:
        package = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        fail("file is not a valid ZIP archive")

    with package:
        return _inspect_package(package, archive, archive_size, max_files,
                                max_expanded_bytes, max_single_file_bytes,
                                status_callback, progress_callback)


def _inspect_package(package, archive, archive_size, max_files,
                     max_expanded_bytes, max_single_file_bytes,
                     status_callback=None, progress_callback=None):
    status = status_callback or (lambda _: None)
    status('正在检查压缩包目录和安全限制…')
    entries = package.infolist()

    if not entries:
        fail("ZIP archive is empty")
    if len(entries) > max_files:
        fail("ZIP contains too many entries")

    normalized_names: list[str] = []
    seen_names: set[str] = set()
    expanded_size = 0
    suspicious_ratios: list[str] = []

    for entry in entries:
        name = normalize_member(entry.filename)
        folded = name.casefold()

        if folded in seen_names:
            fail(f"duplicate or case-colliding path: {name}")
        seen_names.add(folded)
        normalized_names.append(name)

        mode = (entry.external_attr >> 16) & 0o170000
        if stat.S_ISLNK(mode):
            fail(f"symbolic link is not allowed: {name}")

        if entry.flag_bits & 0x1:
            fail(f"encrypted ZIP member is not allowed: {name}")

        if entry.file_size > max_single_file_bytes:
            fail(f"single file exceeds 4 GiB: {name}")

        expanded_size += entry.file_size
        if expanded_size > max_expanded_bytes:
            fail("expanded archive exceeds 16 GiB")

        ratio = entry.file_size / max(entry.compress_size, 1)
        if entry.file_size > 100 * 1024**2 and ratio > 500:
            suspicious_ratios.append(name)

    if suspicious_ratios:
        fail(
            "suspicious compression ratio: "
            + ", ".join(suspicious_ratios[:5])
        )

    file_paths = {name.casefold() for entry, name in zip(entries, normalized_names)
                  if not entry.is_dir()}
    for name in normalized_names:
        if any('/'.join(name.casefold().split('/')[:i]) in file_paths
               for i in range(1, len(name.split('/')))):
            fail(f"file/directory collision: {name}")
    hashes = {}
    actual_total = 0
    last_report = 0.0
    status(f'正在扫描文件完整性，共 {expanded_size / 1024**2:.1f} MiB…')
    for entry, name in zip(entries, normalized_names):
        if entry.is_dir():
            continue
        digest = hashlib.sha256()
        actual = 0
        with package.open(entry) as stream:
            while chunk := stream.read(1024 * 1024):
                actual += len(chunk)
                actual_total += len(chunk)
                if actual > max_single_file_bytes or actual_total > max_expanded_bytes:
                    fail("expanded data exceeds configured limits")
                digest.update(chunk)
                if progress_callback and time.monotonic() - last_report >= 0.2:
                    progress_callback(actual_total, expanded_size + archive_size)
                    last_report = time.monotonic()
        if actual != entry.file_size:
            fail(f"incorrect expanded size: {name}")
        hashes[name] = digest.hexdigest()

    files = [
        name for entry, name in zip(entries, normalized_names)
        if not entry.is_dir()
    ]

    top_parts = {
        PurePosixPath(name).parts[0]
        for name in normalized_names
    }
    has_top_level_file = any(
        len(PurePosixPath(name).parts) == 1
        for name in files
    )

    package_root = (
        next(iter(top_parts))
        if len(top_parts) == 1 and not has_top_level_file
        else None
    )

    def relative_name(name: str) -> str:
        if package_root and name.startswith(package_root + "/"):
            return name[len(package_root) + 1:]
        return name

    relative_files = [relative_name(name) for name in files]
    server_root = None
    client_root = None
    content_profile = None
    declared_runtime = None
    manifest_name = (package_root + '/' if package_root else '') + 'amcl-server-pack.json'
    if manifest_name in files:
        info = next(entry for entry, name in zip(entries, normalized_names) if name == manifest_name)
        if info.file_size > 1024 * 1024:
            fail('server pack manifest is too large')
        manifest = json.loads(package.read(info))
        if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 1:
            fail('unsupported server pack schemaVersion')
        if manifest.get('contentProfile') in ('runtime-and-mods', 'server-content'):
            content_profile = manifest['contentProfile']
        if content_profile == 'server-content':
            declared_runtime = {key: manifest.get(key) for key in ('minecraftVersion', 'loader', 'loaderVersion')
                                if isinstance(manifest.get(key), str) and len(manifest[key]) <= 80}
        def checked_root(key):
            value = manifest.get(key)
            if value is None:
                return None
            if not isinstance(value, str):
                fail(f'invalid {key}')
            value = normalize_member(value)
            if not any(name.startswith(value + '/') for name in relative_files):
                fail(f'{key} is not a populated directory')
            return value
        server_root = checked_root('serverRoot')
        client_root = checked_root('clientRoot')
        if server_root and client_root and (server_root.casefold() == client_root.casefold()
                or server_root.casefold().startswith(client_root.casefold() + '/')
                or client_root.casefold().startswith(server_root.casefold() + '/')):
            fail('serverRoot and clientRoot must not overlap')
        # All other manifest values (especially startCommand) are untrusted hints,
        # never used as executable arguments or authoritative version evidence.
        if server_root:
            relative_files = [name[len(server_root) + 1:] for name in relative_files
                              if name.startswith(server_root + '/')]

    loader = "unknown"
    mc_version = None
    loader_version = None
    start_hint = None

    for name in relative_files:
        forge = re.fullmatch(
            r"libraries/net/minecraftforge/forge/"
            r"([^/]+)/(?:unix|win)_args\.txt",
            name,
        )
        if forge:
            loader = "forge"
            combined = forge.group(1)
            match = re.match(
                r"^(\d+\.\d+(?:\.\d+)?)-(.+)$",
                combined,
            )
            if match:
                mc_version = match.group(1)
                loader_version = match.group(2)
            start_hint = (
                f"java @user_jvm_args.txt @{name} nogui"
            )
            break

        neoforge = re.fullmatch(
            r"libraries/net/neoforged/neoforge/"
            r"([^/]+)/(?:unix|win)_args\.txt",
            name,
        )
        if neoforge:
            loader = "neoforge"
            loader_version = neoforge.group(1)
            start_hint = (
                f"java @user_jvm_args.txt @{name} nogui"
            )
            break

    if loader == "unknown":
        if "fabric-server-launch.jar" in relative_files:
            loader = "fabric"
            start_hint = "java -jar fabric-server-launch.jar nogui"
        elif "server.jar" in relative_files:
            loader = "vanilla-or-custom"
            start_hint = "java -jar server.jar nogui"

    for name in relative_files:
        match = re.fullmatch(
            r"libraries/net/minecraft/server/"
            r"(\d+\.\d+(?:\.\d+)?)/"
            r"server-[^/]+\.jar",
            name,
        )
        if match:
            mc_version = mc_version or match.group(1)
            break

    scripts = sorted(
        name for name in relative_files
        if name.casefold().endswith((
            ".sh",
            ".bat",
            ".cmd",
            ".ps1",
        ))
    )

    status('正在计算整个压缩包的指纹…')
    archive_hash = sha256(archive, (lambda done, total: progress_callback(
        expanded_size + done, expanded_size + total)) if progress_callback else None)
    result = {
        "schemaVersion": 1,
        "ok": True,
        "archive": archive.name,
        "archiveBytes": archive_size,
        "sha256": archive_hash,
        "fileCount": len(files),
        "expandedBytes": expanded_size,
        "packageRoot": package_root,
        "serverRoot": server_root,
        "clientRoot": client_root,
        "contentProfile": content_profile,
        "declaredRuntime": declared_runtime,
        "loader": loader,
        "minecraftVersion": mc_version,
        "loaderVersion": loader_version,
        "requiredJava": required_java(mc_version),
        "startHint": start_hint,
        "containsEula": "eula.txt" in relative_files,
        "containsServerProperties":
            "server.properties" in relative_files,
        "containsJvmArgs":
            "user_jvm_args.txt" in relative_files,
        "scriptsFound": scripts[:20],
        "scriptsWereExecuted": False,
        "files": hashes,
        "kind": "server" if (server_root or start_hint or "server.properties" in relative_files
                                 or "amcl-server-pack.json" in relative_files) else "client-or-unknown",
    }
    return result


def main():
    try:
        if len(sys.argv) != 2:
            fail("usage: archive_inspection.py <zip-or-mrpack>")
        print(json.dumps(inspect_archive(sys.argv[1]), ensure_ascii=False, indent=2))
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
