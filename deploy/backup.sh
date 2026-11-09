#!/usr/bin/env bash
# Sauvegarde de production : bases (coordinateur, paiements, IA), règlements
# d'époques et journaux. À mettre en cron quotidien, par exemple :
#   0 4 * * * /chemin/vers/depot/deploy/backup.sh >> /var/log/odysseus-backup.log 2>&1
#
# Exclusions volontaires : caches de modèles (data/huggingface, data/local,
# ré-installables) et clés SSH Cookbook (data/ssh — à sauvegarder séparément,
# chiffré). Copiez les archives HORS du serveur (rclone, restic, S3…).
set -euo pipefail

cd "$(dirname "$0")/.."
STAMP="$(date +%F_%H%M%S)"
mkdir -p backups

tar czf "backups/odysseus_${STAMP}.tar.gz" \
    --exclude='data/huggingface' \
    --exclude='data/local' \
    --exclude='data/ssh' \
    data logs 2>/dev/null || true

# Rétention locale : 14 jours.
find backups -name 'odysseus_*.tar.gz' -mtime +14 -delete

echo "[$(date -Is)] backup OK -> backups/odysseus_${STAMP}.tar.gz ($(du -h "backups/odysseus_${STAMP}.tar.gz" | cut -f1))"
