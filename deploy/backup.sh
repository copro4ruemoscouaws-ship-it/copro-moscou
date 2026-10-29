#!/usr/bin/env bash
# Sauvegarde nocturne de la base SQLite vers S3 (les documents sont déjà dans S3).
# Cron (sudo crontab -u copro -e) :   15 3 * * *  /srv/copro/app/deploy/backup.sh
set -euo pipefail
set -a; source /etc/copro.env; set +a

STAMP=$(date +%Y-%m-%d)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# .backup produit une copie cohérente même si le site est en cours d'utilisation
sqlite3 "$DB_PATH" ".backup '$TMP/copro.db'"
gzip "$TMP/copro.db"
/srv/copro/venv/bin/python - "$TMP/copro.db.gz" "$S3_BUCKET" "sauvegardes/copro-$STAMP.db.gz" <<'PY'
import sys, boto3
boto3.client("s3").upload_file(sys.argv[1], sys.argv[2], sys.argv[3],
                               ExtraArgs={"ServerSideEncryption": "AES256"})
PY
echo "Sauvegarde envoyée : s3://$S3_BUCKET/sauvegardes/copro-$STAMP.db.gz"
