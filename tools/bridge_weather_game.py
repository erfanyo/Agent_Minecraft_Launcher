"""Launch an isolated test client, type /ai, verify feedback and saved weather."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher import resolve_inherited_json, build_launch_command
from os_platform.process import external_process_environment
from tools.bridge_weather_test import run_case, PROMPT, write_json
from tools.bridge_game_input import send_chat, close_window, click_client, press_key, system_close


def prepare_world(source, destination, cheats):
    import nbtlib
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('session.lock'))
    level = nbtlib.load(destination / 'level.dat')
    data = level['Data']
    data['allowCommands'] = nbtlib.Byte(cheats)
    data['raining'] = nbtlib.Byte(0)
    data['thundering'] = nbtlib.Byte(0)
    data['rainTime'] = nbtlib.Int(12000)
    data['thunderTime'] = nbtlib.Int(12000)
    data['LevelName'] = nbtlib.String('AMCL Bridge Weather Test')
    data['GameRules']['doWeatherCycle'] = nbtlib.String('false')
    level.save()


def test_game(source_instance, world, jar, *, cheats=True, startup_timeout=300, world_source=None):
    import nbtlib
    source = Path(source_instance).resolve(strict=True)
    if source.name == '地下酒吧':
        raise ValueError('地下酒吧 is excluded from testing')
    saves = (source / 'saves').resolve()
    supplied_template = world_source is not None
    world_source = Path(world_source).resolve(strict=True) if supplied_template else (saves / world).resolve(strict=True)
    if '地下酒吧' in world_source.parts:
        raise ValueError('地下酒吧 is excluded from testing')
    if not supplied_template and not world_source.is_relative_to(saves):
        raise ValueError('World must be inside this instance saves directory')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 26100)) == 0:
            raise RuntimeError('Bridge port 26100 is already in use; close the other bridge game first')
    install = source.parent.parent
    work = ROOT / '.tmp' / ('bridge-weather-' + uuid.uuid4().hex[:8])
    work.mkdir(parents=True)
    (work / 'mods').mkdir()
    shutil.copyfile(jar, work / 'mods' / jar.name)
    prepare_world(world_source, work / 'saves/WeatherTest', cheats)
    (work / 'options.txt').write_text('lang:en_us\nrenderDistance:2\nsimulationDistance:2\n'
        'fullscreen:false\npauseOnLostFocus:false\nguiScale:2\n', encoding='utf-8')
    detail = resolve_inherited_json(source.name, str(install))
    main_class = detail.get('mainClass', '')
    if main_class not in ('net.fabricmc.loader.impl.launch.knot.KnotClient',
                          'cpw.mods.bootstraplauncher.BootstrapLauncher',
                          'cpw.mods.modlauncher.Launcher', 'net.minecraft.launchwrapper.Launch'):
        raise ValueError('Unsupported client entry point: ' + main_class)
    major = detail.get('javaVersion', {}).get('majorVersion', 8 if '1.16.5' in source.name or '1.12.2' in source.name else 17 if '1.18.2' in source.name or '1.19.2' in source.name else 21)
    if major <= 8:
        java = next((install / 'runtime/jre-8').rglob('java.exe'))
    elif major <= 17:
        java = ROOT / '.tmp/jdk/jdk-17.0.20.1+1/bin/java.exe'
    else:
        java = next((install / 'runtime/jre-21').rglob('java.exe'))
    command = build_launch_command(detail, str(work), str(java), username='BridgeTester',
                                  memory_gb=2, assets_dir=str(install/'assets'), install_dir=str(install))
    legacy_menu = any(version in source.name for version in ('1.12.2', '1.16.5', '1.18.2', '1.19.2'))
    if not legacy_menu:
        command += ['--quickPlaySingleplayer', 'WeatherTest']
    command += ['--width', '854', '--height', '480']
    report = {'cheats': cheats, 'work': str(work), 'jar': jar.name, 'instance': source.name,
              'jarSHA256': hashlib.sha256(jar.read_bytes()).hexdigest()}
    with (work / 'client-output.log').open('wb') as output, external_process_environment() as environment:
        process = subprocess.Popen(command, cwd=work, stdout=output, stderr=subprocess.STDOUT,
            env=environment, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        report['testPID'] = process.pid
        try:
            deadline = time.monotonic() + startup_timeout
            log = work / 'logs/latest.log'
            menu_entered = False
            while time.monotonic() < deadline and process.poll() is None:
                text = log.read_text(encoding='utf-8', errors='replace') if log.exists() else ''
                if legacy_menu and not menu_entered and ('Sound engine started' in text or 'Sound Library started' in text):
                    time.sleep(8)
                    click_client(process.pid, .5, .45)  # Singleplayer, GUI scale 2.
                    time.sleep(2)
                    click_client(process.pid, .5, .28)  # Only isolated test world.
                    time.sleep(.1)
                    click_client(process.pid, .5, .28)
                    menu_entered = True
                if 'logged in with entity id' in text and ((work / '.bridge/token.txt').exists() or (work / '.bridge').exists() and legacy_menu):
                    break
                time.sleep(.2)
            else:
                raise TimeoutError('Test client did not enter the world; inspect client-output.log')
            time.sleep(20 if legacy_menu else 3)  # Legacy loading screens outlive server login.
            # Creating a Qt application here changes Windows DPI awareness,
            # invalidating LWJGL 2 menu coordinates mid-test. Use protocol and
            # saved world data as the oracle; keep screenshots out of this run.
            result = []
            started_ms = time.time() * 1000
            def responder():
                try:
                    result.append(run_case(work / '.bridge', expect='success' if cheats else 'denied',
                                           started_ms=started_ms, request_timeout=20, result_timeout=15))
                except Exception as error:
                    result.append({'passed': False, 'error': str(error)})
            thread = threading.Thread(target=responder, daemon=True)
            thread.start()
            send_chat(process.pid, '/ai ' + PROMPT)
            thread.join(timeout=40)
            if thread.is_alive():
                raise TimeoutError('Weather responder timed out')
            report['bridge'] = result[0]
        except Exception as error:
            report['error'] = str(error)
        finally:
            if process.poll() is None:
                try:
                    if '1.12.2' in source.name:
                        press_key(process.pid, 0x1B)
                        time.sleep(.5)
                        click_client(process.pid, .5, .725)  # Save and Quit to Title.
                        time.sleep(5)
                        system_close(process.pid)
                    else:
                        close_window(process.pid)
                    process.wait(timeout=45)
                except (RuntimeError, subprocess.TimeoutExpired):
                    process.terminate()
                    process.wait(timeout=10)
                    report['forcedShutdown'] = True
            report['exitCode'] = process.returncode
    level = nbtlib.load(work / 'saves/WeatherTest/level.dat')
    report['worldRaining'] = bool(level['Data']['raining'])
    report['passed'] = (report.get('bridge', {}).get('passed', False)
                        and report['worldRaining'] == cheats and not report.get('forcedShutdown')
                        and report['exitCode'] == 0)
    report['worldWeatherVerified'] = not report.get('forcedShutdown', False)
    write_json(work / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', required=True, type=Path)
    parser.add_argument('--world', required=True)
    parser.add_argument('--world-source', type=Path, help='Read-only seed world to copy; never downgrade a newer world')
    parser.add_argument('--jar', required=True, type=Path)
    parser.add_argument('--case', choices=('allowed', 'denied', 'both'), default='both')
    args = parser.parse_args(argv)
    cases = [True, False] if args.case == 'both' else [args.case == 'allowed']
    reports = []
    for cheats in cases:
        report = test_game(args.instance, args.world, args.jar, cheats=cheats, world_source=args.world_source)
        reports.append(report)
        print(('PASS' if report['passed'] else 'FAIL') + ': ' + report['work'], flush=True)
    return 0 if all(report['passed'] for report in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
