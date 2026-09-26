# Distribution contract

This file records the Windows package layout so future contributors can change
the release pipeline without mixing user data into release archives.

## Windows variants

1. **Standard** — `AgentMinecraftLauncher.exe`. It is a single-file executable;
   the launcher creates its `AMCL` data directory beside the executable as
   needed.
2. **Preinstalled local AI** — `AgentMinecraftLauncher-Windows-LocalAI.zip`.
   It contains exactly the launcher executable, the pinned built-in GGUF at
   `AMCL/models/<registered filename>`, and `CreateDesktopShortcut.bat`.
   The model is verified against `model_registry.RESOURCES` before it enters
   the archive. Do not copy the build machine's whole `AMCL` directory: it can
   contain settings, credentials, logs, and unrelated user data.

Running the BAT creates a Desktop shortcut whose target and working directory
are the extracted bundle's current absolute path. If that folder is moved,
users must run the BAT again to refresh the shortcut. The launcher itself stays
portable and will create any other missing AMCL data folders when needed.

## Bundled wallpaper

`assets/-7878592509531134518.png` is the original 2560×1494 Minecraft
screenshot supplied by the project owner from the `画质测试` instance on
2026-09-25. The filename is the world's seed, `-7878592509531134518`.
This world was the owner's first attempt at high-quality Minecraft visuals,
so the seed name preserves its personal history. Both PyInstaller specs
include the image under `assets/`; the runtime
loads it from the source tree or PyInstaller extraction directory. New
installations select `bundled` by default. Existing saved wallpaper choices
are preserved, including `none`. Do not load this asset from the portable
`AMCL` data directory: the standard Windows release must remain a single EXE.

The PNG is 8,720,844 bytes before packaging. If replacing or recompressing it,
update `ui_background.BUNDLED_WALLPAPER` and both spec files together.

## Build and CI

`build_release.ps1` builds both variants. `tools/build_local_ai_bundle.py`
downloads the registered local model when it is absent, checks its SHA256, and
creates the ZIP. A failure to obtain or validate that file must fail the release
build instead of silently producing a bundle advertised as preinstalled.
`SHA256SUMS.txt` covers both Windows deliverables. The manual Windows CI job
uploads both variants; Linux packaging remains the separate `onedir` tarball.

If the model registry filename or digest changes, review this packaging script
and the AI install/detection logic together. CI package scripts must not pull in
user-local config or API keys.
