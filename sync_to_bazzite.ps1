# AMCL -> bazzite VM incremental sync (PowerShell)
# Usage: .\sync_to_bazzite.ps1
# Sync changed files to bazzite VM via SSH (erfanyo@10.77.0.40, key: bazzite_vm)
# Project at /home/erfanyo/amcl
#
# By default: sync all uncommitted changes (git diff HEAD).
# Pass -Minutes 60 to use timestamp-based scan instead (last 60 min).

param([int]$Minutes = 0, [string[]]$Files = @())

$ErrorActionPreference = "Stop"
$REMOTE = "bazzite"
$REMOTE_DIR = "/home/erfanyo/amcl"
$LOCAL = $PSScriptRoot
$backupDir = "$REMOTE_DIR/.sync-backups/$(Get-Date -Format 'yyyyMMdd-HHmmss')"

Write-Host "[sync] Scanning changed files..." -ForegroundColor Cyan

if ($Files.Count -gt 0) {
    $changed = $Files
} elseif ($Minutes -gt 0) {
    # Timestamp mode: files modified in the last N minutes
    $cutoff = (Get-Date).AddMinutes(-$Minutes)
    $changed = Get-ChildItem -Recurse -File -Path $LOCAL |
        Where-Object {
            $_.LastWriteTime -gt $cutoff -and
            $_.FullName -notmatch '\\\.venv\\|\\__pycache__\\|\\\.tmp\\|\\dist\\|\\dist_070\\|\\build\\|\\\.minecraft\\|\\AMCL\\|\\related-projects\\|\\local-maintenance\\|\\archives\\|\\outputs\\|\\00-工作区入口\\' -and
            $_.Extension -match '\.(py|json|md|txt|spec)$'
        } | ForEach-Object {
            $_.FullName.Substring($LOCAL.Length + 1).Replace('\', '/')
        }
} else {
    # Git mode (default): all uncommitted changes (staged + unstaged + untracked)
    Push-Location $LOCAL
    $gitFiles = git diff --name-only HEAD 2>$null
    # Do not upload unrelated untracked workspaces or credentials.
    $gitUntracked = git ls-files --others --exclude-standard 2>$null
    Pop-Location
    $allGit = @()
    if ($gitFiles) { $allGit += $gitFiles }
    if ($gitUntracked) { $allGit += $gitUntracked }
    # Deduplicate and filter
    $changed = $allGit | Sort-Object -Unique | Where-Object {
        $_ -match '\.(py|json|md|txt|spec|ini|toml|ps1|sh|java|gradle|kts)$' -and
        $_ -notmatch '^\.' -and
        $_ -notmatch '^dist' -and
        $_ -notmatch '^build' -and
        $_ -notmatch '^\.venv' -and
        $_ -notmatch '^AMCL' -and
        $_ -notmatch '^(acl-recovery|comfy|host_fixes|outputs|related-projects|local-maintenance|archives|00-工作区入口)/'
    }
}

if (-not $changed -or $changed.Count -eq 0) {
    Write-Host "[sync] No changed files. Nothing to sync." -ForegroundColor Yellow
    exit 0
}

Write-Host "[sync] Syncing $($changed.Count) files to bazzite..." -ForegroundColor Cyan

foreach ($rel in $changed) {
    if ($rel -match "(^|/)\.\.(/|$)|:|'" -or $rel.StartsWith('/')) {
        throw "Invalid relative path: $rel"
    }
    $localFile = Join-Path $LOCAL ($rel -replace '/', '\')
    if (-not (Test-Path $localFile)) { continue }
    $targetDir = "$REMOTE_DIR/" + [System.IO.Path]::GetDirectoryName($rel).Replace('\', '/')
    $backupFile = "$backupDir/$rel"
    $backupParent = $backupFile.Substring(0, $backupFile.LastIndexOf('/'))
    ssh -o BatchMode=yes -o ConnectTimeout=10 $REMOTE "mkdir -p '$targetDir' '$backupParent' && if test -f '$REMOTE_DIR/$rel'; then cp -p '$REMOTE_DIR/$rel' '$backupFile'; fi"
    if ($LASTEXITCODE -ne 0) { throw "Remote preparation failed: $rel" }
    scp -q -o BatchMode=yes -o ConnectTimeout=10 $localFile "${REMOTE}:${REMOTE_DIR}/$rel"
    if ($LASTEXITCODE -ne 0) { throw "Copy failed: $rel" }
    Write-Host "  $rel" -ForegroundColor DarkGray
}

Write-Host "[sync] Done. $($changed.Count) files synced." -ForegroundColor Green
Write-Host "[sync] Previous remote files: $backupDir"
