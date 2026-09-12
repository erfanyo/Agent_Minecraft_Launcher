#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="${AMCL_WSL_VENV:-$HOME/.cache/amcl-wsl-test-venv}"

cd "$ROOT"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更高版本"'

if [[ ! -x "$VENV/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r requirements.txt

export QT_QPA_PLATFORM=offscreen
export AML_DATA_DIR="${AMCL_WSL_DATA_DIR:-$HOME/.cache/amcl-wsl-test-data}"
"$VENV/bin/python" ci_smoke.py
"$VENV/bin/python" -m compileall -q -x '[\\/](build|dist|\.git|\.venv)[\\/]' .
"$VENV/bin/python" -m unittest discover -v

echo "WSL TEST OK: import、编译和完整自动测试均通过"

if [[ "${1:-}" == "--gui" ]]; then
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        echo "没有检测到 WSLg 图形环境，跳过界面启动。" >&2
        exit 2
    fi
    unset QT_QPA_PLATFORM
    exec "$VENV/bin/python" main.py
fi
