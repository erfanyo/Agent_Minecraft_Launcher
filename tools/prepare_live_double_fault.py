"""Create an Iris-enhanced clone of the preserved live baseline."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--instance", default="double-baseline")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    root = Path(args.root).resolve()
    if root.exists():
        raise ValueError("Use a new output directory; double-fault records are never overwritten")
    source_meta = json.loads((source_root / "baseline.json").read_text(encoding="utf-8"))
    game = Path(source_meta["game_root"])
    source = source_root / "frozen-baseline"
    destination = game / "versions" / args.instance
    if destination.exists():
        raise ValueError(f"Destination instance already exists: {destination}")

    root.mkdir(parents=True)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("logs", "crash-reports", "session.lock"))
    old_id = source_meta["instance"]
    old_json = destination / f"{old_id}.json"
    old_jar = destination / f"{old_id}.jar"
    detail = json.loads(old_json.read_text(encoding="utf-8"))
    detail["id"] = args.instance
    old_json.unlink()
    write(destination / f"{args.instance}.json", detail)
    old_jar.rename(destination / f"{args.instance}.jar")

    import paths
    paths.set_game_dir(str(game))
    from agent_tools import install_mod
    installed = install_mod("iris", args.instance, game_dir=str(game))
    if not installed.startswith("已安装 "):
        raise RuntimeError(installed)
    iris_files = sorted(p.name for p in (destination / "mods").glob("iris-*.jar"))
    if len(iris_files) != 1:
        raise RuntimeError(f"Expected one active Iris file, found: {iris_files}")
    write(root / "baseline.json", {
        "instance": args.instance,
        "game_root": str(game),
        "minecraft": "1.21.1",
        "neoforge": "21.1.250",
        "java": 21,
        "source_frozen_baseline": str(source),
        "iris": iris_files[0],
        "installation_result": installed,
        "verification": "installed_not_launched",
    })
    print(installed)
    print(f"Prepared {args.instance} at {destination}")


if __name__ == "__main__":
    main()
