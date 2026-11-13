#!/usr/bin/env bash
# Runs ON the Runpod pod: fine-tune Run B on HER2match, evaluate before/after, package, stop the pod.
#
#   bash scripts/pod/finetune_her2match.sh
#
# Expects (uploaded by the launcher, scripts/pod/launch_finetune.py):
#   /workspace/her2_code.tgz     code + configs
#   /workspace/her2_replay.tgz   per-class subset of our patches (fit / val / holdout), same paths as data/raw
#   /workspace/run_b_best.pt     the checkpoint to start from
# Downloads HER2match's tiles.zip (7.4 GB, Zenodo, public) and unpacks only the IHC tiles.
#
# Cost guards: HARD_LIMIT_MIN (default 120) watchdog; the pod stops itself on exit unless KEEP_POD=1.
set -uo pipefail
mkdir -p /workspace/logs /workspace/her2
LOG=/workspace/logs/finetune.log
exec > >(tee -a "$LOG") 2>&1
stop_pod() {
  echo "[$(date +%T)] finetune.sh exiting"
  if [ "${KEEP_POD:-0}" != "1" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    sleep "${RESULT_GRACE_SEC:-900}"   # window for the launcher to copy results
    echo "[$(date +%T)] stopping pod $RUNPOD_POD_ID"
    runpodctl stop pod "$RUNPOD_POD_ID" || runpodctl pod stop "$RUNPOD_POD_ID" || true
  fi
}
trap stop_pod EXIT
( sleep $(( ${HARD_LIMIT_MIN:-120} * 60 )); echo "[$(date +%T)] HARD LIMIT reached"; runpodctl stop pod "${RUNPOD_POD_ID:-x}" ) &

cd /workspace/her2
tar -xzf /workspace/her2_code.tgz --no-same-owner
echo "[$(date +%T)] GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
python -c "import sys, torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok); sys.exit(0 if ok else 3)" \
  || { echo "PyTorch cannot use the GPU on this host: aborting"; exit 3; }
python -m pip install -q --break-system-packages pyyaml scikit-image scikit-learn pillow scipy 2>&1 | tail -1
command -v unzip >/dev/null || { apt-get update -qq && apt-get install -y -qq unzip >/dev/null; }

mkdir -p data/raw data/external/her2match artifacts/v2/run_b /workspace/dl
tar -xzf /workspace/her2_replay.tgz --no-same-owner -C . || { echo "replay archive failed"; exit 1; }
cp /workspace/run_b_best.pt artifacts/v2/run_b/best.pt
echo "[$(date +%T)] replay patches: $(find data/raw -type f | wc -l)"

if [ ! -d data/external/her2match/IHC/train ]; then
  echo "[$(date +%T)] downloading HER2match tiles.zip"
  for i in 1 2 3 4 5 6 7 8; do
    curl -sSfL -C - --retry 5 -o /workspace/dl/tiles.zip "https://zenodo.org/api/records/15797050/files/tiles.zip/content" && break
    echo "  retry $i"; sleep 30
  done
  unzip -q -o /workspace/dl/tiles.zip 'IHC/*' -d data/external/her2match || { echo "tiles.zip unzip failed"; exit 1; }
  rm -f /workspace/dl/tiles.zip
fi
curl -sSfL -o data/external/her2match/HER2match_scores.csv "https://zenodo.org/api/records/15797050/files/HER2match_scores.csv/content"
echo "[$(date +%T)] HER2match IHC tiles: $(find data/external/her2match/IHC -name '*.jpg' | wc -l)"

python scripts/train_v2.py --config configs/v2_ft_her2match.yaml --eval || echo "[$(date +%T)] training FAILED (exit $?)"
mkdir -p artifacts/v2/ft_her2match/baseline_run_b
python - <<'PY' || echo "baseline eval FAILED"
import sys; sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from pathlib import Path
from train_v2 import load_config
from scripts.eval_v2 import evaluate_run
cfg = load_config("configs/v2_ft_her2match.yaml")
cfg["run_name"] = "run_b (before fine-tuning)"
evaluate_run(cfg, Path("artifacts/v2/ft_her2match/baseline_run_b"), checkpoint=Path("artifacts/v2/run_b/best.pt"))
PY
tar -czf /workspace/results_ft_her2match.tgz --exclude=last.pt -C artifacts/v2 ft_her2match /workspace/logs 2>/dev/null
echo "[$(date +%T)] packaged /workspace/results_ft_her2match.tgz ($(du -h /workspace/results_ft_her2match.tgz | cut -f1))"
touch /workspace/DONE
echo "[$(date +%T)] ALL DONE"
