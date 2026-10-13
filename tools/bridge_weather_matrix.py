"""Run installed BridgeMod targets sequentially, retaining each failure report."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.bridge_weather_game import test_game
from tools.bridge_weather_test import write_json

TARGETS = {
    'forge-1.19.2': '1.19.2-forge-43.5.2',
    'forge-1.16.5': '1.16.5-forge-36.2.42',
    'forge-1.18.2': '1.18.2-forge-40.3.12',
    'fabric-1.20.1': 'fabric-loader-0.19.5-1.20.1',
    'forge-1.20.1': '1.20.1-forge-47.4.0',
    'forge-1.12.2': '1.12.2-forge-14.23.5.2864',
    'fabric-1.21.1': 'fabric-loader-0.19.5-1.21.1',
    'neoforge-1.21.1': 'neoforge-21.1.252',
}


def classic_seed():
    """Minimal pre-flattening world metadata; never downgrade a newer save."""
    import nbtlib as n
    folder = ROOT / '.tmp/bridge-classic-seed'
    folder.mkdir(parents=True, exist_ok=True)
    data = n.Compound({'LevelName': n.String('Bridge Seed'), 'version': n.Int(19133),
        'RandomSeed': n.Long(42), 'generatorName': n.String('default'),
        'generatorVersion': n.Int(1), 'generatorOptions': n.String(''),
        'GameType': n.Int(1), 'Difficulty': n.Byte(1), 'initialized': n.Byte(1),
        'MapFeatures': n.Byte(1), 'SpawnX': n.Int(0), 'SpawnY': n.Int(80),
        'SpawnZ': n.Int(0), 'Time': n.Long(0), 'DayTime': n.Long(0),
        'GameRules': n.Compound({'doWeatherCycle': n.String('false')})})
    n.File({'Data': data}, gzipped=True).save(folder / 'level.dat')
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', nargs='+', choices=TARGETS, default=list(TARGETS))
    parser.add_argument('--report', type=Path, default=ROOT / '.tmp/bridge-matrix-report.json')
    args = parser.parse_args(argv)
    reports = []
    for target in args.targets:
        source = ROOT / '.minecraft/versions' / TARGETS[target]
        template = None
        if target == 'forge-1.12.2':
            template = classic_seed()
        elif target in ('forge-1.18.2', 'fabric-1.20.1', 'forge-1.20.1'):
            template = ROOT / '.minecraft/versions/1.16.5-forge-36.2.42/saves/新的世界'
        for cheats in (True, False):
            print(f'RUN {target}: {"allowed" if cheats else "denied"}', flush=True)
            try:
                result = test_game(source, '新的世界', ROOT / f'bridge-mod/dist/agentmc-bridge-{target}-0.2.0.jar',
                                   cheats=cheats, world_source=template)
            except Exception as error:
                result = {'passed': False, 'error': str(error)}
            result['target'] = target
            result['case'] = 'allowed' if cheats else 'denied'
            reports.append(result)
            write_json(args.report, {'passed': all(r['passed'] for r in reports), 'cases': reports})
            print(f'{"PASS" if result["passed"] else "FAIL"} {target}: {result.get("work", result.get("error"))}', flush=True)
    return 0 if all(r['passed'] for r in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
