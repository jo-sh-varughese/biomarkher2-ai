#!/usr/bin/env bash
# Run ON THE SDC VM, from the copied bundle folder (the one holding images.tar.gz):
#   sudo bash deploy/install.sh
# Installs BioMarkHER2 into /opt/biomarkher2 (override with BIOMARK_HOME) and starts it.
# Safe to re-run: existing .env, accounts, reviews and slides are kept.
set -euo pipefail
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${BIOMARK_HOME:-/opt/biomarkher2}"
APP_UID=10001

[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is not installed: run deploy/install_docker_ubuntu.sh first." >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 plugin missing (docker compose)." >&2; exit 1; }

echo "== 1. Verify the bundle"
(cd "$BUNDLE" && sha256sum -c SHA256SUMS)

echo "== 2. Load images"
gunzip -c "$BUNDLE/images.tar.gz" | docker load

echo "== 3. Lay out $HOME_DIR"
mkdir -p "$HOME_DIR"/{artifacts,slides,certs,backups}
cp "$BUNDLE/deploy/docker-compose.yml" "$BUNDLE/deploy/Caddyfile" "$HOME_DIR/"
cp "$BUNDLE/deploy/"*.sh "$HOME_DIR/"
[ -f "$HOME_DIR/.env" ] || cp "$BUNDLE/deploy/.env.example" "$HOME_DIR/.env"

echo "== 4. Models"
tar -xzf "$BUNDLE/biomark_models.tgz" -C "$HOME_DIR"
(cd "$HOME_DIR" && sha256sum -c artifacts/MODELS.sha256)
chown -R "$APP_UID" "$HOME_DIR/artifacts" "$HOME_DIR/slides"
chmod 700 "$HOME_DIR/artifacts" "$HOME_DIR/backups"

echo "== 5. Start"
cd "$HOME_DIR"
docker compose up -d
echo "Waiting for the models to load (up to 3 minutes) ..."
for _ in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8000/api/health && echo
docker compose ps

echo
echo "== Next"
echo "1. Check $HOME_DIR/.env (hostname, TLS, site name, scanner um/px), then: cd $HOME_DIR && docker compose up -d"
echo "2. Create the first administrator:"
echo "     docker compose -f $HOME_DIR/docker-compose.yml exec app python -m app.admin_cli create-admin --email <email> --name \"<name>\""
echo "   (or open the one-time setup link printed by: docker compose logs app | grep setup)"
echo "3. Run $HOME_DIR/smoke_test.sh and add the nightly backup (Deployment Guide, Backups)."
