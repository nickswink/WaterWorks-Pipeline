#!/bin/bash
# -----------------------------------------------------------------------------
# ccr_sync.sh - nightly sync of Consumer Confidence Reports
#
# Mounts the corporate file share, copies the published CCR reports into the
# public website's reports directory, and unmounts. Runs from cron as root.
# Exits 0 even on failure so a transient file-server outage never leaves the
# share mounted or spams cron mail.
# -----------------------------------------------------------------------------
set -u

MOUNT=/mnt/ccr
DEST=/opt/wwp-portal/reports
LOG=/var/log/ccr_sync.log

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null; }

cleanup() {
    if mountpoint -q "$MOUNT"; then
        umount "$MOUNT" 2>/dev/null || true
    fi
}
trap cleanup EXIT

mkdir -p "$MOUNT" "$DEST"

if ! mount "$MOUNT" 2>>"$LOG"; then
    log "WARN could not mount $MOUNT (file server unreachable?); skipping sync"
    exit 0
fi

if [ -d "$MOUNT" ]; then
    rsync -rt --include='CCR_*.txt' --include='*/' --exclude='*' \
        "$MOUNT"/ "$DEST"/ 2>>"$LOG" \
        && log "OK CCR reports synced to $DEST" \
        || log "WARN rsync reported errors"
fi

exit 0
