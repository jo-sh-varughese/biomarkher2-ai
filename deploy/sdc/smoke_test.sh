#!/usr/bin/env bash
# Post-install / post-update checks, run on the VM:  bash /opt/biomarkher2/smoke_test.sh
set -uo pipefail
HOME_DIR="${BIOMARK_HOME:-/opt/biomarkher2}"
cd "$HOME_DIR"
# .env is read by Docker Compose; values may contain spaces, so take only what is needed (never source it).
BIOMARK_HOSTNAME="$(grep -E '^BIOMARK_HOSTNAME=' .env | tail -1 | cut -d= -f2- | tr -d '"')"
fail=0
check() { if eval "$2" >/dev/null 2>&1; then echo "  OK    $1"; else echo "  FAIL  $1"; fail=1; fi; }

echo "BioMarkHER2 smoke test ($BIOMARK_HOSTNAME)"
check "containers running"               "[ \$(docker compose ps --status running -q | wc -l) -ge 2 ]"
check "app healthy (docker healthcheck)"  "docker inspect --format '{{.State.Health.Status}}' \$(docker compose ps -q app) | grep -q healthy"
check "both models loaded"                "curl -fsS http://127.0.0.1:8000/api/health | grep -q '\"prescore_model\": true'"
check "model checksums"                   "sha256sum -c artifacts/MODELS.sha256"
check "HTTPS answers"                     "curl -fsSk https://$BIOMARK_HOSTNAME/api/health"
check "HTTP redirects to HTTPS"           "curl -s -D - -o /dev/null http://$BIOMARK_HOSTNAME/ | grep -qi '^location: https://'"
check "secure-cookie mode on (HSTS sent)" "curl -sk -D - -o /dev/null https://$BIOMARK_HOSTNAME/ | grep -qi strict-transport-security"
check "port 8000 not exposed beyond VM"   "! ss -ltn | grep -E '(0\.0\.0\.0|\[::\]):8000 '"
check "slides folder writable by the app" "docker compose exec -T app sh -c 'touch data/slides/.w && rm data/slides/.w'"
check "disk below 80%"                    "[ \$(df --output=pcent $HOME_DIR | tail -1 | tr -dc 0-9) -lt 80 ]"
echo "Site gate: $(docker compose logs app 2>/dev/null | grep -m1 'gate:' | sed 's/.*gate: //')"
exit $fail
