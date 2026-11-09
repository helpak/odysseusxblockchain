#!/usr/bin/env bash
# Production backup: databases (coordinator, payments, AI), epoch
# settlements and logs. Run it daily from cron, for example:
#   0 4 * * * /path/to/repo/deploy/backup.sh >> /var/log/odysseus-backup.log 2>&1
#
# Deliberately excluded: model caches (data/huggingface, data/local,
# reinstallable) and Cookbook SSH keys (data/ssh — back these up separately,
# encrypted). Copy the archives OFF the server (rclone, restic, S3…).
set -euo pipefail

cd "$(dirname "$0")/.."
STAMP="$(date +%F_%H%M%S)"
mkdir -p backups

tar czf "backups/odysseus_${STAMP}.tar.gz" \
    --exclude='data/huggingface' \
    --exclude='data/local' \
    --exclude='data/ssh' \
    data logs 2>/dev/null || true

# Local retention: 14 days.
find backups -name 'odysseus_*.tar.gz' -mtime +14 -delete

echo "[$(date -Is)] backup OK -> backups/odysseus_${STAMP}.tar.gz ($(du -h "backups/odysseus_${STAMP}.tar.gz" | cut -f1))"
