#!/bin/bash
#
# nightly_config_backup.sh - archive key /etc configuration on this server
#
# Owner : IT Helpdesk (group "helpdesk" maintains the include list)
# Runs  : as root from /etc/cron.d/it-config-backup
# Output: /var/backups/it/<host>-etc-YYYY-MM-DD.tar.gz  (kept 14 days)
# Log   : /var/log/it-config-backup.log
#
# 2024-02-12 KT  initial version
# 2025-06-03 DW  add sshd_config.d, sudoers.d
# 2026-09-30 DW  overwrite the daily archive instead of piling up; retention 14d
#
set -u

BACKUP_DIR="/var/backups/it"
RETENTION_DAYS=14
HOST="$(hostname -s)"
STAMP="$(date +%F)"
DEST="${BACKUP_DIR}/${HOST}-etc-${STAMP}.tar.gz"

# Paths are relative to / (tar -C /). Add new items at the end.
INCLUDE=(
    etc/hostname
    etc/hosts
    etc/resolv.conf
    etc/network/interfaces
    etc/apt/sources.list
    etc/apt/sources.list.d
    etc/ssh/sshd_config
    etc/ssh/sshd_config.d
    etc/crontab
    etc/cron.d
    etc/sudoers.d
    etc/passwd
    etc/group
    etc/login.defs
    etc/pam.d/common-password
)

log() {
    echo "$(date '+%F %T') [config-backup] $*"
}

mkdir -p "${BACKUP_DIR}"
chmod 0700 "${BACKUP_DIR}"

present=()
for item in "${INCLUDE[@]}"; do
    if [ -e "/${item}" ]; then
        present+=("${item}")
    fi
done

if tar -C / -czf "${DEST}.tmp" "${present[@]}" 2>/dev/null; then
    mv -f "${DEST}.tmp" "${DEST}"
    chmod 0600 "${DEST}"
    log "OK ${DEST} ($(du -h "${DEST}" | cut -f1), ${#present[@]} paths)"
else
    rm -f "${DEST}.tmp"
    log "FAILED creating ${DEST}"
    exit 1
fi

find "${BACKUP_DIR}" -maxdepth 1 -name "${HOST}-etc-*.tar.gz" -mtime +"${RETENTION_DAYS}" -delete

exit 0
