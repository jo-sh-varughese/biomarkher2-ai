#!/usr/bin/env bash
# Nightly backup of everything BioMarkHER2 records (accounts, audit log, reviews,
# case database, annotations, learning store, shadow log). Model files and slides
# are NOT included: models are re-installable from the bundle; slides are large
# and follow SDC's own retention / backup policy.
#
#   sudo /opt/biomarkher2/backup.sh            # manual
#   cron: 30 1 * * * root /opt/biomarkher2/backup.sh >> /var/log/biomark-backup.log 2>&1
set -euo pipefail
HOME_DIR="${BIOMARK_HOME:-/opt/biomarkher2}"
KEEP_DAYS="${BIOMARK_BACKUP_KEEP_DAYS:-14}"
STAMP="$(date +%Y-%m-%d_%H%M)"
cd "$HOME_DIR"

# Consistent copies of the SQLite databases, taken inside the running container
# with SQLite's online backup API (safe while users are working).
docker compose exec -T app python - <<'PY'
import sqlite3, pathlib
out = pathlib.Path("artifacts/.backup_snapshot"); out.mkdir(exist_ok=True)
for name in ("biomark.db", "cases.sqlite3"):
    src = pathlib.Path("artifacts") / name
    if src.exists():
        with sqlite3.connect(src) as s, sqlite3.connect(out / name) as d:
            s.backup(d)
print("sqlite snapshot ok")
PY

rm -rf db_snapshot && mv artifacts/.backup_snapshot db_snapshot
# Live database files are skipped (their consistent copies are in db_snapshot/);
# restore = put db_snapshot/* back into artifacts/.
tar -czf "backups/biomark_$STAMP.tgz" \
  --exclude='artifacts/biomark.db*' --exclude='artifacts/cases.sqlite3*' \
  --exclude='artifacts/phase2_unet_8epochs' --exclude='artifacts/v2' \
  artifacts db_snapshot .env Caddyfile docker-compose.yml
rm -rf db_snapshot
find backups -name 'biomark_*.tgz' -mtime +"$KEEP_DAYS" -delete
ls -la "backups/biomark_$STAMP.tgz"
