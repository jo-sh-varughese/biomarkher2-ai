#!/usr/bin/env bash
# Bundle exactly the model files a deployment needs (docs/DEPLOYMENT.md) into
# dist/biomark_models.tgz with a SHA-256 manifest, for copying to the server.
#
#   bash scripts/package_models.sh          # on the machine that has artifacts/
#   tar -xzf biomark_models.tgz             # on the server, inside the repo
#   sha256sum -c artifacts/MODELS.sha256    # verify nothing was corrupted
set -euo pipefail
cd "$(dirname "$0")/.."
FILES=(
  artifacts/phase2_unet/best.pt                       # stain map (pixel intensity classes)
  artifacts/phase2_unet/conformal_calibration.npz     # its pixel-level conformal calibration
  artifacts/phase2_unet/conformal_calibration_ids.json
  artifacts/v2/run_b/best.pt                          # AI pre-score (multi-task U-Net, ResNet-50)
  artifacts/v2/run_b/prescore_sets.json               # its conformal prediction-set calibration (training site)
  artifacts/tumour/best.pt                            # invasive-tumour segmenter (whole slides)
)
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
sha256sum "${FILES[@]}" > artifacts/MODELS.sha256
mkdir -p dist
tar -czf dist/biomark_models.tgz "${FILES[@]}" artifacts/MODELS.sha256
ls -la dist/biomark_models.tgz
cat artifacts/MODELS.sha256
