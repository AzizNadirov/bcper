#!/usr/bin/env bash
# backupd — periodic backup to cloud (rclone) with N-version retention
# Usage: backupd.sh [--config /path/to/backupd.conf] [--dry-run] [--now]

set -euo pipefail

# ── defaults ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${BACKUPD_CONFIG:-$SCRIPT_DIR/backupd.conf}"
DRY_RUN=false
FORCE_NOW=false

# ── colour output ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $*"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${RESET} $*"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${RESET} $*"; }
die()  { echo -e "${RED}[$(date '+%H:%M:%S')] ✗${RESET} $*" >&2; exit 1; }

# ── argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)   CONFIG_FILE="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=true; shift ;;
    --now)      FORCE_NOW=true; shift ;;
    --help|-h)
      echo -e "${BOLD}backupd${RESET} — backup dirs to cloud with version retention"
      echo ""
      echo "  Options:"
      echo "    --config <path>   Path to config file (default: ./backupd.conf)"
      echo "    --dry-run         Print what would happen, make no changes"
      echo "    --now             Run immediately, ignoring SCHEDULE"
      echo "    --help            Show this help"
      exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

# ── load config ───────────────────────────────────────────────────────────────
[[ -f "$CONFIG_FILE" ]] || die "Config not found: $CONFIG_FILE"
# shellcheck source=/dev/null
source "$CONFIG_FILE"

# required config keys
: "${REMOTE:?REMOTE must be set in config (e.g. gdrive:backups)}"
: "${KEEP_VERSIONS:?KEEP_VERSIONS must be set in config (e.g. 5)}"
: "${BACKUP_DIRS:?BACKUP_DIRS array must be set in config}"
: "${LOG_FILE:?LOG_FILE must be set in config}"

LABEL="${LABEL:-backupd}"
RCLONE_FLAGS="${RCLONE_FLAGS:---transfers 4 --checkers 8 --contimeout 60s --timeout 300s --retries 3 --low-level-retries 10 --stats 1m}"
STAMP_FORMAT="${STAMP_FORMAT:-%Y-%m-%dT%H-%M-%S}"
COMPRESS="${COMPRESS:-false}"
EXCLUDE_PATTERNS="${EXCLUDE_PATTERNS:-}"

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v rclone >/dev/null 2>&1 || die "rclone not found. Install: https://rclone.org/install/"
mkdir -p "$(dirname "$LOG_FILE")"

exec > >(tee -a "$LOG_FILE") 2>&1

log "${BOLD}backupd${RESET} starting — label=${LABEL}"
$DRY_RUN && warn "DRY-RUN mode — no changes will be made"

# ── schedule check ────────────────────────────────────────────────────────────
if [[ "$FORCE_NOW" == false && -n "${SCHEDULE:-}" ]]; then
  LOCK_FILE="/tmp/backupd_${LABEL}.lock"
  LAST_RUN=0
  [[ -f "$LOCK_FILE" ]] && LAST_RUN=$(cat "$LOCK_FILE")
  NOW_EPOCH=$(date +%s)
  DIFF=$(( NOW_EPOCH - LAST_RUN ))

  case "$SCHEDULE" in
    hourly)  INTERVAL=3600 ;;
    daily)   INTERVAL=86400 ;;
    weekly)  INTERVAL=604800 ;;
    *)
      # numeric seconds
      if [[ "$SCHEDULE" =~ ^[0-9]+$ ]]; then
        INTERVAL=$SCHEDULE
      else
        die "Unknown SCHEDULE value: $SCHEDULE (use hourly/daily/weekly or seconds)"
      fi
      ;;
  esac

  if (( DIFF < INTERVAL )); then
    NEXT=$(( LAST_RUN + INTERVAL - NOW_EPOCH ))
    log "Skipping — next run in ${NEXT}s. Use --now to force."
    exit 0
  fi
fi

# ── stamp ─────────────────────────────────────────────────────────────────────
STAMP=$(date +"$STAMP_FORMAT")

# ── build exclude flags ───────────────────────────────────────────────────────
EXCLUDE_FLAGS=()
# shellcheck disable=SC2153
for pat in $EXCLUDE_PATTERNS; do
  EXCLUDE_FLAGS+=(--exclude "$pat")
done

# ── backup each directory ─────────────────────────────────────────────────────
ERRORS=0
for src_dir in "${BACKUP_DIRS[@]}"; do
  [[ -d "$src_dir" ]] || { warn "Directory not found, skipping: $src_dir"; (( ERRORS++ )) || true; continue; }

  # sanitise path → remote folder name (strip leading slash, replace / with _)
  rel="${src_dir#/}"
  folder_name="${rel//\//_}"
  dest="${REMOTE}/${folder_name}/${STAMP}"

  log "Backing up: ${BOLD}$src_dir${RESET} → ${BOLD}$dest${RESET}"

  if [[ "$COMPRESS" == true ]]; then
    # create a tarball, upload it, then delete temp file
    TMP_TAR="/tmp/backupd_${folder_name}_${STAMP}.tar.gz"
    log "  Compressing…"
    $DRY_RUN || tar -czf "$TMP_TAR" -C "$(dirname "$src_dir")" "$(basename "$src_dir")" 2>/dev/null
    if [[ "$DRY_RUN" == false ]]; then
      # shellcheck disable=SC2086
      rclone copyto $RCLONE_FLAGS "$TMP_TAR" "${dest}.tar.gz" \
        && ok "  Uploaded compressed archive" \
        || { warn "  Upload failed for $src_dir"; (( ERRORS++ )) || true; }
      rm -f "$TMP_TAR"
    else
      log "  [dry-run] would upload $TMP_TAR → ${dest}.tar.gz"
    fi
  else
    # sync directory contents
    if [[ "$DRY_RUN" == false ]]; then
      # shellcheck disable=SC2086
      rclone copy $RCLONE_FLAGS "${EXCLUDE_FLAGS[@]}" "$src_dir/" "$dest/" \
        && ok "  Synced $src_dir" \
        || { warn "  Sync failed for $src_dir"; (( ERRORS++ )) || true; }
    else
      log "  [dry-run] would rclone copy $src_dir/ → $dest/"
    fi
  fi

  # ── version retention ──────────────────────────────────────────────────────
  log "  Pruning versions — keeping last $KEEP_VERSIONS for $folder_name"
  if [[ "$DRY_RUN" == false ]]; then
    # list all timestamped snapshots, sorted oldest-first
    mapfile -t all_versions < <(
      rclone lsf "${REMOTE}/${folder_name}/" --dirs-only 2>/dev/null \
        | sed 's|/$||' \
        | sort
    )
    total=${#all_versions[@]}
    to_delete=$(( total - KEEP_VERSIONS ))

    if (( to_delete > 0 )); then
      for (( i=0; i<to_delete; i++ )); do
        old="${REMOTE}/${folder_name}/${all_versions[$i]}"
        log "  Deleting old snapshot: ${all_versions[$i]}"
        rclone purge "$old" 2>/dev/null \
          && ok "  Deleted $old" \
          || warn "  Could not delete $old"
      done
    else
      ok "  No pruning needed ($total / $KEEP_VERSIONS versions kept)"
    fi
  else
    log "  [dry-run] would prune versions, keeping last $KEEP_VERSIONS"
  fi
done

# ── record run timestamp ──────────────────────────────────────────────────────
if [[ "$DRY_RUN" == false ]]; then
  LOCK_FILE="/tmp/backupd_${LABEL}.lock"
  date +%s > "$LOCK_FILE"
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
if (( ERRORS == 0 )); then
  ok "${BOLD}All backups completed successfully${RESET} (stamp: $STAMP)"
else
  warn "${BOLD}Backup finished with $ERRORS error(s)${RESET} — check log: $LOG_FILE"
  exit 1
fi
