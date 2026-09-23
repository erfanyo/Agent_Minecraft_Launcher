# AMCL -> bazzite VM incremental sync (PowerShell)
# Usage: .\sync_to_bazzite.ps1
# Sync changed files to bazzite VM via SSH (erfanyo@10.77.0.40, key: bazzite_vm)
# Project at /home/erfanyo/amcl
#
# By default: sync all uncommitted changes (git diff HEAD).
# Pass -Minutes 60 to use timestamp-based scan instead (last 60 min).

param([int]$Minutes = 0)

$ErrorActionPreference = "Stop"
$REMOTE = "bazzite"
$REMOTE_DIR = "/home/erfanyo/amcl"
$LOCAL = "E:\Agent_Minecraft_Launcher 0.0.1"

Write-Host "[sync] Scanning changed files..." -ForegroundColor Cyan

if ($Minutes -gt 0) {
    # Timestamp mode: files modified in the last N minutes
    $cutoff = (Get-Date).AddMinutes(-$Minutes)
    $changed = Get-ChildItem -Recurse -File -Path $LOCAL |
        Where-Object {
            $_.LastWriteTime -gt $cutoff -and
            $_.FullName -notmatch '\\\.venv\\|\\__pycache__\\|\\\.tmp\\|\\dist\\|\\dist_070\\|\\build\\|\\\.minecraft\\|\\AMCL\\' -and
            $_.Extension -match '\.(py|json|md|txt|spec)$'
        } | ForEach-Object {
            $_.FullName.Substring($LOCAL.Length + 1).Replace('\', '/')
        }
} else {
    # Git mode (default): all uncommitted changes (staged + unstaged + untracked)
    Push-Location $LOCAL
    $gitFiles = git diff --name-only HEAD 2>$null
    $gitUntracked = git ls-files --others --exclude-standard 2>$null
    Pop-Location
    $allGit = @()
    if ($gitFiles) { $allGit += $gitFiles }
    if ($gitUntracked) { $allGit += $gitUntracked }
    # Deduplicate and filter
    $changed = $allGit | Sort-Object -Unique | Where-Object {
        $_ -match '\.(py|json|md|txt|spec)$' -and
        $_ -notmatch '^\.' -and
        $_ -notmatch '^dist' -and
        $_ -notmatch '^build' -and
        $_ -notmatch '^\.venv' -and
        $_ -notmatch '^AMCL'
    }
}

if (-not $changed -or $changed.Count -eq 0) {
    Write-Host "[sync] No changed files. Nothing to sync." -ForegroundColor Yellow
    exit 0
}

Write-Host "[sync] Syncing $($changed.Count) files to bazzite..." -ForegroundColor Cyan

foreach ($rel in $changed) {
    $localFile = Join-Path $LOCAL ($rel -replace '/', '\')
    if (-not (Test-Path $localFile)) { continue }
    $targetDir = "$REMOTE_DIR/" + [System.IO.Path]::GetDirectoryName($rel).Replace('\', '/')
    ssh $REMOTE "mkdir -p '$targetDir'" 2>$null
    scp -q $localFile "${REMOTE}:${REMOTE_DIR}/$rel"
    Write-Host "  $rel" -ForegroundColor DarkGray
}

Write-Host "[sync] Done. $($changed.Count) files synced." -ForegroundColor Green
