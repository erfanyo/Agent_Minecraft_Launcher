# AMCL -> PVE container 104 incremental sync (PowerShell)
# Usage: .\sync_to_pve.ps1
# Push changed files directly into container rootfs via PVE host.
# Uses `pct push` — instant local filesystem copy, no SSH into container.
#
# PVE host: 10.77.0.1 (root), Container: 104 (bazzite)
# Project inside container: /root/amcl/

$ErrorActionPreference = "Stop"
$PVE_HOST = "10.77.0.1"
$PVE_USER = "root"
$CTID = "104"
$REMOTE_DIR = "/root/amcl"
$LOCAL = "E:\Agent_Minecraft_Launcher 0.0.1"
$CUTOFF = (Get-Date).AddMinutes(-30)

Write-Host "[sync] Scanning changed files..." -ForegroundColor Cyan

$changed = Get-ChildItem -Recurse -File -Path $LOCAL |
    Where-Object {
        $_.LastWriteTime -gt $CUTOFF -and
        $_.FullName -notmatch '\\\.venv\\|\\__pycache__\\|\\\.tmp\\|\\dist\\|\\dist_070\\|\\build\\|\\\.minecraft\\|\\AMCL\\' -and
        $_.Extension -match '\.(py|json|md|txt|spec)$'
    }

if ($changed.Count -eq 0) {
    Write-Host "[sync] No recently changed files. Nothing to sync." -ForegroundColor Yellow
    exit 0
}

Write-Host "[sync] Pushing $($changed.Count) files into container $CTID via PVE host..." -ForegroundColor Cyan

$baseLen = $LOCAL.Length + 1
foreach ($f in $changed) {
    $rel = $f.FullName.Substring($baseLen).Replace('\', '/')
    $containerPath = "$REMOTE_DIR/$rel"
    # Ensure target directory exists inside container
    $containerDir = [System.IO.Path]::GetDirectoryName($containerPath).Replace('\', '/')
    ssh "${PVE_USER}@${PVE_HOST}" "pct exec $CTID -- mkdir -p '$containerDir'" 2>$null
    # Push file: scp to PVE host temp, then pct push into container
    $tempPath = "/tmp/amcl-sync-$([System.Guid]::NewGuid().ToString('N').Substring(0,6))-$([System.IO.Path]::GetFileName($rel))"
    scp -q $f.FullName "${PVE_USER}@${PVE_HOST}:$tempPath"
    ssh "${PVE_USER}@${PVE_HOST}" "pct push $CTID '$tempPath' '$containerPath' && rm -f '$tempPath'" 2>$null
    Write-Host "  $rel" -ForegroundColor DarkGray
}

Write-Host "[sync] Done. $($changed.Count) files pushed into container $CTID." -ForegroundColor Green
Write-Host "[sync] Enter container: ssh $PVE_USER@$PVE_HOST 'pct enter $CTID'" -ForegroundColor Cyan
