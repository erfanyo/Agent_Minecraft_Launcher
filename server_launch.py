"""Validated, GUI-free launch plans; never execute package shell scripts."""
import os
from pathlib import Path
import re
import shlex
import zipfile
from safe_paths import safe_child
from archive_inspection import required_java


def local_file(root, relative):
    path = Path(safe_child(root, relative))
    current = Path(root)
    for part in relative.replace('\\', '/').split('/'):
        current = current / part
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            raise ValueError('启动文件不能经过链接或目录联接')
    if not path.is_file():
        raise ValueError(f'服务端缺少文件：{relative}，请先补全安装。')
    return path


def _tokens(path):
    if path.stat().st_size > 256 * 1024:
        raise ValueError('启动参数文件过大')
    # Accept a conservative subset of Java argfile syntax; reject escaped and
    # continued lines rather than interpreting them differently from Java.
    text = path.read_text(encoding='utf-8-sig')
    if '\\' in text or '\x00' in text:
        raise ValueError('启动参数包含暂不支持的转义写法，请使用正斜杠路径。')
    args = shlex.split(text, comments=True, posix=True)
    if any(arg.startswith('@') for arg in args):
        raise ValueError('不允许嵌套参数文件')
    return args


def _classpath(root, value, separator):
    for name in value.split(separator):
        if not name.startswith('libraries/'):
            raise ValueError('加载器依赖必须位于服务端 libraries 目录内')
        local_file(root, name)


def _executable_root_jars(root):
    """Return root JARs that declare a non-installer Main-Class."""
    result = []
    for jar in sorted(root.glob('*.jar')):
        name = jar.name.lower()
        if any(part in name for part in ('installer', 'sources', 'javadoc')):
            continue
        try:
            if jar.is_symlink() or jar.stat().st_size > 1024 ** 3:
                continue
            with zipfile.ZipFile(jar) as archive:
                info = archive.getinfo('META-INF/MANIFEST.MF')
                if info.file_size > 256 * 1024:
                    continue
                text = archive.read(info).decode('utf-8', 'replace')
            # Manifest continuation lines start with one space.
            logical = []
            for line in text.replace('\r\n', '\n').split('\n'):
                if line.startswith(' ') and logical:
                    logical[-1] += line[1:]
                else:
                    logical.append(line)
            main = next((line.split(':', 1)[1].strip() for line in logical
                         if line.lower().startswith('main-class:')), '')
            if main and 'installer' not in main.lower():
                result.append(jar.name)
        except (OSError, KeyError, zipfile.BadZipFile):
            continue
    return result


def _jar_plan(root, relative, user_args, loader='custom-jar'):
    local_file(root, relative)
    return {'entry': relative, 'loader': loader, 'minecraftVersion': None,
            'requiredJava': None,
            'arguments': user_args + ['-jar', relative, 'nogui']}


def build_launch_plan(root, platform=None, selected_jar=None):
    root = Path(root).resolve(strict=True)
    windows = (os.name == 'nt') if platform is None else platform == 'windows'
    filename = 'win_args.txt' if windows else 'unix_args.txt'
    entries = []
    for loader, base in [('forge', 'libraries/net/minecraftforge/forge'),
                         ('neoforge', 'libraries/net/neoforged/neoforge')]:
        parent = root / base
        if parent.is_dir():
            for version in parent.iterdir():
                if (version / filename).is_file():
                    entries.append((loader, f'{base}/{version.name}/{filename}'))
    if len(entries) > 1:
        raise ValueError('发现多个加载器启动入口，请先移除旧入口或使用单一版本服务端包。')
    user_args = []
    if (root / 'user_jvm_args.txt').exists():
        user_args = _tokens(local_file(root, 'user_jvm_args.txt'))
        for arg in user_args:
            if not re.fullmatch(r'-X(?:ms|mx|ss)\d+[kKmMgG]|-XX:[+-](?:UseG1GC|UseZGC|UseParallelGC|UseSerialGC)', arg):
                raise ValueError(f'需人工检查的 JVM 参数：{arg}。目前仅接受内存大小和常用 GC 开关。')
    if selected_jar:
        candidate = Path(selected_jar)
        if candidate.is_absolute():
            try:
                candidate = candidate.resolve(strict=True).relative_to(root)
            except (OSError, ValueError):
                raise ValueError('启动 JAR 必须位于当前服务端目录内')
        relative = candidate.as_posix()
        if candidate.suffix.lower() != '.jar' or relative.startswith('../'):
            raise ValueError('请选择当前服务端目录内的 JAR 文件')
        jar = local_file(root, relative)
        if jar.suffix.lower() != '.jar':
            raise ValueError('启动入口必须是 JAR 文件')
        return _jar_plan(root, relative, user_args)
    if entries:
        loader, entry = entries[0]
        args = _tokens(local_file(root, entry))
        mains = {'cpw.mods.bootstraplauncher.BootstrapLauncher',
                 'net.neoforged.fml.startup.Server'}
        main_seen = False
        mc = None
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in mains and not main_seen:
                main_seen = True
            elif not main_seen and arg in ('-p', '--module-path', '-cp', '--class-path'):
                i += 1
                if i >= len(args):
                    raise ValueError('启动参数缺少路径')
                _classpath(root, args[i], ';' if windows else ':')
            elif not main_seen and arg.startswith('-DlegacyClassPath='):
                _classpath(root, arg.split('=', 1)[1], ';' if windows else ':')
            elif not main_seen and arg == '-DlibraryDirectory=libraries':
                pass
            elif not main_seen and re.fullmatch(r'-Djava\.net\.preferIPv6Addresses=(?:true|false|system)', arg):
                pass
            elif not main_seen and re.fullmatch(r'-Djava\.net\.preferIPv4Stack=(?:true|false)', arg):
                pass
            elif not main_seen and re.fullmatch(r'-D(?:ignoreList|mergeModules)=[\w.,+\-]+', arg):
                pass
            elif not main_seen and arg in ('--add-modules', '--add-opens', '--add-exports'):
                i += 1
                if i >= len(args) or not re.fullmatch(r'[\w./=,\-]+', args[i]):
                    raise ValueError('无效的 Java 模块参数')
            elif not main_seen and re.fullmatch(r'--(?:add-modules|add-opens|add-exports)=[\w./=,\-]+', arg):
                pass
            elif main_seen and arg in ('--launchTarget', '--fml.forgeVersion', '--fml.mcVersion',
                                       '--fml.forgeGroup', '--fml.mcpVersion', '--fml.neoForgeVersion',
                                       '--fml.neoFormVersion'):
                i += 1
                if i >= len(args) or not re.fullmatch(r'[\w.+\-]+', args[i]):
                    raise ValueError('无效的加载器参数')
                if arg == '--launchTarget' and args[i] not in ('forgeserver', 'neoforgeserver'):
                    raise ValueError('不是服务端启动目标')
                if arg == '--fml.mcVersion':
                    mc = args[i]
            else:
                raise ValueError(f'暂不支持或不安全的启动参数：{arg}')
            i += 1
        if not main_seen:
            raise ValueError('没有识别到加载器服务端主类')
        if not mc and loader == 'forge':
            mc = entry.split('/')[-2].split('-')[0]
        # NeoForge 20.2+ uses <MC minor>.<MC patch>.<build> versioning.
        if not mc and loader == 'neoforge':
            bits = entry.split('/')[-2].split('.')
            if len(bits) >= 3 and bits[0].isdigit() and bits[1].isdigit():
                mc = f'1.{bits[0]}.{bits[1]}'
        return {'entry': entry, 'loader': loader, 'minecraftVersion': mc,
                'requiredJava': required_java(mc), 'arguments': user_args + args + ['nogui']}
    # Old Forge generations launch a root forge-*.jar. Modern incomplete Forge
    # installs must not silently fall back to a vanilla server.jar.
    loader_roots = any((root / base).exists() for base in (
        'libraries/net/minecraftforge/forge', 'libraries/net/neoforged/neoforge'))
    executable_jars = _executable_root_jars(root)
    if loader_roots:
        loader_jars = [name for name in executable_jars
                       if re.search(r'(?:^|[-_.])(?:neo)?forge(?:[-_.]|$)', name, re.I)]
        if len(loader_jars) == 1:
            loader = 'neoforge' if 'neoforge' in loader_jars[0].lower() else 'forge'
            return _jar_plan(root, loader_jars[0], user_args, loader)
        if len(loader_jars) > 1:
            raise ValueError('发现多个可启动的 Forge JAR，请在「服务端管理」中指定一个：'
                             + '、'.join(loader_jars))
        raise ValueError(f'缺少当前平台的 {filename}，请补全服务端安装。')
    for jar, loader in [('fabric-server-launch.jar', 'fabric'), ('server.jar', 'vanilla-or-custom')]:
        if (root / jar).exists():
            local_file(root, jar)
            return _jar_plan(root, jar, user_args, loader)
    if len(executable_jars) == 1:
        return _jar_plan(root, executable_jars[0], user_args)
    if len(executable_jars) > 1:
        raise ValueError('发现多个可启动 JAR，请在「服务端管理」中指定一个：'
                         + '、'.join(executable_jars))
    raise ValueError('未找到可验证的服务端入口；可使用「补全运行库」安装 Forge/NeoForge，不会执行包内脚本。')


def eula_accepted(root):
    path = Path(root) / 'eula.txt'
    if not path.exists():
        return False
    text = local_file(root, 'eula.txt').read_text(encoding='utf-8-sig')
    value = ''
    for line in text.splitlines():
        if not line.lstrip().startswith(('#', '!')) and '=' in line:
            key, candidate = line.split('=', 1)
            if key.strip() == 'eula':
                value = candidate.strip()
    return value.lower() == 'true'
