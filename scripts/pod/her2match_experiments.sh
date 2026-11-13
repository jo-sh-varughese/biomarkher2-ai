#!/usr/bin/env bash
# Runs ON the Runpod pod: HER2match stain profile, Run B raw vs stain-normalised, two improved fine-tunes,
# all scored on the same held-out sets; then packages results and stops the pod.
# Expects /workspace/her2_code.tgz, /workspace/her2_replay.tgz, /workspace/run_b_best.pt (see launch_finetune.py).
set -uo pipefail
mkdir -p /workspace/logs /workspace/her2
LOG=/workspace/logs/experiments.log
exec > >(tee -a "$LOG") 2>&1
stop_pod() {
  echo "[$(date +%T)] experiments.sh exiting"
  if [ "${KEEP_POD:-0}" != "1" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    sleep "${RESULT_GRACE_SEC:-900}"; runpodctl stop pod "$RUNPOD_POD_ID" || true
  fi
}
trap stop_pod EXIT
( sleep $(( ${HARD_LIMIT_MIN:-90} * 60 )); echo "[$(date +%T)] HARD LIMIT reached"; runpodctl stop pod "${RUNPOD_POD_ID:-x}" ) &

cd /workspace/her2
tar -xzf /workspace/her2_code.tgz --no-same-owner
echo "[$(date +%T)] GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
python -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 3)" || { echo "no usable GPU"; exit 3; }
python -m pip install -q --break-system-packages pyyaml scikit-image scikit-learn pillow scipy 2>&1 | tail -1
command -v unzip >/dev/null || { apt-get update -qq && apt-get install -y -qq unzip >/dev/null; }
mkdir -p data/raw data/external/her2match artifacts/v2/run_b /workspace/dl
tar -xzf /workspace/her2_replay.tgz --no-same-owner -C .
cp /workspace/run_b_best.pt artifacts/v2/run_b/best.pt
if [ ! -d data/external/her2match/IHC/train ]; then
  for i in 1 2 3 4 5 6 7 8; do
    curl -sSfL -C - --retry 5 -o /workspace/dl/tiles.zip "https://zenodo.org/api/records/15797050/files/tiles.zip/content" && break; sleep 30
  done
  unzip -q -o /workspace/dl/tiles.zip 'IHC/*' -d data/external/her2match || { echo "unzip failed"; exit 1; }
  rm -f /workspace/dl/tiles.zip
fi
curl -sSfL -o data/external/her2match/HER2match_scores.csv "https://zenodo.org/api/records/15797050/files/HER2match_scores.csv/content"
echo "[$(date +%T)] tiles: $(find data/external/her2match/IHC -name '*.jpg' | wc -l), replay: $(find data/raw -type f | wc -l)"

python scripts/fit_her2match_profile.py || { echo "profile FAILED"; exit 1; }

echo "[$(date +%T)] ===== baseline: Run B, raw and stain-normalised ====="
mkdir -p artifacts/v2/baseline_run_b
python - <<'PY' || echo "baseline FAILED"
import sys; sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from pathlib import Path
from train_v2 import load_config
from scripts.eval_v2 import evaluate_run
cfg = load_config("configs/v2_ft2_raw.yaml"); cfg["run_name"] = "baseline_run_b"
evaluate_run(cfg, Path("artifacts/v2/baseline_run_b"), checkpoint=Path("artifacts/v2/run_b/best.pt"))
PY
for V in raw norm; do
  echo "[$(date +%T)] ===== fine-tune ft2_$V ====="
  python scripts/train_v2.py --config configs/v2_ft2_$V.yaml --eval || echo "ft2_$V FAILED"
done
cp configs/site_profiles/her2_ihc_40x_vs_bci_her2match.json artifacts/v2/
tar -czf /workspace/results_experiments.tgz --exclude=last.pt -C artifacts/v2 baseline_run_b ft2_raw ft2_norm her2_ihc_40x_vs_bci_her2match.json /workspace/logs 2>/dev/null
echo "[$(date +%T)] packaged $(du -h /workspace/results_experiments.tgz | cut -f1)"
touch /workspace/DONE; echo "[$(date +%T)] ALL DONE"
