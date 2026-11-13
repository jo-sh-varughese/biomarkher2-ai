#!/usr/bin/env bash
# Run on the BUILD machine (internet, Docker, the repo with artifacts/).
# Produces dist/sdc_bundle/: everything the SDC VM needs, with no internet on the VM:
#   images.tar.gz        the app image + the Caddy image (docker save)
#   biomark_models.tgz   the model files + artifacts/MODELS.sha256
#   deploy/              this folder (compose file, Caddyfile, .env.example, scripts)
#   SHA256SUMS           checksums of the above
#
#   bash deploy/sdc/make_offline_bundle.sh [image-tag]
set -euo pipefail
cd "$(dirname "$0")/../.."
TAG="${1:-sdc-2026.11.11}"
CADDY="caddy:2-alpine"
OUT=dist/sdc_bundle
rm -rf "$OUT" && mkdir -p "$OUT/deploy"

docker image inspect "biomarkher2:$TAG" >/dev/null 2>&1 || docker build --platform linux/amd64 -t "biomarkher2:$TAG" .
docker pull --platform linux/amd64 "$CADDY"
echo "Saving images (about 1-2 GB compressed) ..."
docker save "biomarkher2:$TAG" "$CADDY" | gzip -1 > "$OUT/images.tar.gz"

bash scripts/package_models.sh
cp dist/biomark_models.tgz "$OUT/"

cp deploy/sdc/docker-compose.yml deploy/sdc/Caddyfile deploy/sdc/.env.example deploy/sdc/*.sh deploy/sdc/README.md "$OUT/deploy/"
{
  echo "image biomarkher2:$TAG $(docker image inspect --format '{{.Id}}' "biomarkher2:$TAG")"
  echo "image $CADDY $(docker image inspect --format '{{.Id}}' "$CADDY")"
} > "$OUT/IMAGES.txt"
(cd "$OUT" && sha256sum images.tar.gz biomark_models.tgz IMAGES.txt deploy/* > SHA256SUMS)
ls -la "$OUT"
echo "Copy $OUT to the VM (scp -r), then on the VM: sudo bash deploy/install.sh"
