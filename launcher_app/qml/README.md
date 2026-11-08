# Qt Quick experiment

This is an opt-in shell. It does not replace the production Widgets entry point.

```bash
python qml_main.py
```

The shell connects to AMCL's real `InstanceCatalogService`, `LaunchRequest` /
`LaunchPreparationController`, `BackgroundTask`, and `GameSessionController`.
The representative flow is: scan local instances → choose one → prepare its
launch plan in a cancellable worker → explicitly confirm → start the game.
The existing Java selection, auth, and file preparation rules are reused through
`LaunchRequest`; the game process is started through `GameSessionController`.

Resources and the agent page are intentionally labeled as incomplete. Resource
search/download, AI tool calls, edit previews, rollback, wallpaper controls,
localization, and the full existing settings surface have not been connected to this
prototype. The QML copy is currently English-only. Use `python main.py` for the
complete Widgets experience. No web mock is involved.

For a Linux headless smoke run, install the normal PySide6 system dependencies
and use a software Quick backend if needed:

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m pytest tests/qml
```

The test covers model binding, QML compilation/navigation, and an offscreen
render. An offscreen render is not a native-window compatibility test and is
not evidence of screen FPS.
