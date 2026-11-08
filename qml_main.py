"""Opt-in Qt Quick frontend entry point; the Widgets launcher remains main.py."""
from launcher_app.qml_main import main

if __name__ == "__main__":
    raise SystemExit(main())
