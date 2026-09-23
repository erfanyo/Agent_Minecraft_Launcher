#!/bin/bash
# AMCL -> PVE container 104 incremental sync (Bash/WSL version)
# Usage: ./sync_to_pve.sh
# Push changed files directly into container rootfs via PVE host.
# Uses `pct push` — instant local filesystem copy, no SSH into container.

set -e
PVE_HOST="10.77.0.1"
PVE_USER="root"
CTID="104"
REMOTE_DIR="/root/amcl"
LOCAL_DIR="E:/Agent_Minecraft_Launcher 0.0.1"

echo "[sync] Scanning changed files..."

# Find recently modified files (last 30 min), exclude heavy dirs
CHANGED=$(find "$LOCAL_DIR" -type f -mmin -30 \
  \( -name "*.py" -o -name "*.json" -o -name "*.md" -o -name "*.txt" -o -name "*.spec" \) \
  ! -path "*/.venv/*" ! -path "*/__pycache__/*" ! -path "*/.tmp/*" \
  ! -path "*/dist/*" ! -path "*/dist_070/*" ! -path "*/build/*" \
  ! -path "*/.minecraft/*" ! -path "*/AMCL/*" 2>/dev/null)

if [ -z "$CHANGED" ]; then
  echo "[sync] No recently changed files. Nothing to sync."
  exit 0
fi

COUNT=$(echo "$CHANGED" | wc -l)
echo "[sync] Pushing $COUNT files into container $CTID via PVE host..."

BASE_LEN=${#LOCAL_DIR}
for f in $CHANGED; do
  REL="${f:$BASE_LEN+1}"
  CONTAINER_PATH="$REMOTE_DIR/$REL"
  CONTAINER_DIR=$(dirname "$CONTAINER_PATH")
  
  # Ensure target directory exists inside container
  ssh "${PVE_USER}@${PVE_HOST}" "pct exec $CTID -- mkdir -p '$CONTAINER_DIR'" 2>/dev/null
  
  # Push file via PVE host (scp to temp, then pct push into container)
  TEMP_PATH="/tmp/amcl-sync-$$-$(basename "$REL")"
  scp -q "$f" "${PVE_USER}@${PVE_HOST}:$TEMP_PATH"
  ssh "${PVE_USER}@${PVE_HOST}" "pct push $CTID '$TEMP_PATH' '$CONTAINER_PATH' && rm -f '$TEMP_PATH'" 2>/dev/null
  
  echo "  $REL"
done

echo "[sync] Done. $COUNT files pushed into container $CTID."
echo "[sync] Enter container: ssh ${PVE_USER}@${PVE_HOST} 'pct enter $CTID'"
