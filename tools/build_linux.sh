#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXE="${PYTHON_EXE:-python3}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/dist-linux}"
PACKAGE_NAME="AgentMinecraftLauncher-linux-x86_64.tar.gz"

cd "$ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Linux package must be built on Linux." >&2
    exit 1
fi

echo "==> Prepare verified bundled components"
"$PYTHON_EXE" tools/fetch_llamacpp.py
"$PYTHON_EXE" tools/fetch_bridge_mod_jars.py
"$PYTHON_EXE" tools/verify_release_inputs.py

echo "==> Build PyInstaller onedir package"
rm -rf "$OUTPUT_DIR"
"$PYTHON_EXE" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$OUTPUT_DIR" \
    AgentMinecraftLauncher-linux.spec

PROGRAM="$OUTPUT_DIR/AgentMinecraftLauncher/AgentMinecraftLauncher"
if [[ ! -x "$PROGRAM" ]]; then
    echo "Packaged executable missing: $PROGRAM" >&2
    exit 1
fi

echo "==> Verify frozen package startup"
SMOKE_DATA="$(mktemp -d)"
trap 'rm -rf "$SMOKE_DATA"' EXIT
QT_QPA_PLATFORM=offscreen AML_DATA_DIR="$SMOKE_DATA" \
    timeout 90s "$PROGRAM" --amcl-ci-smoke
if command -v xvfb-run >/dev/null 2>&1; then
    QT_QPA_PLATFORM=xcb QT_OPENGL=software LIBGL_ALWAYS_SOFTWARE=1 \
        AML_DATA_DIR="$SMOKE_DATA" xvfb-run -a \
        timeout 90s "$PROGRAM" --amcl-ci-smoke
fi

echo "==> Create tar.gz and checksums"
tar -C "$OUTPUT_DIR" -czf "$OUTPUT_DIR/$PACKAGE_NAME" AgentMinecraftLauncher
(
    cd "$OUTPUT_DIR"
    sha256sum "$PACKAGE_NAME" > SHA256SUMS-linux.txt
)

echo "LINUX PACKAGE OK: $OUTPUT_DIR/$PACKAGE_NAME"
