#!/usr/bin/env bash
# Runs ON the Runpod pod. One command: data -> train -> evaluate -> package -> stop the pod.
#
#   bash scripts/pod/run.sh configs/v2_run0_gpu_check.yaml configs/v2_run_a.yaml
#
# Budget guards (the whole programme has $6.72 -- docs/V2_TRAINING_PLAN.md):
#   * HARD_LIMIT_MIN (default 200): a watchdog stops the pod after this many
#     minutes no matter what is running.
#   * MIN_TILES_PER_S (default 40): after the first config, if training
#     throughput is below this the remaining configs are skipped -- a slow or
#     CPU-starved pod is abandoned instead of paid for by the hour.
#   * The pod is stopped on exit, success or failure, unless KEEP_POD=1.
#     (Stopping ends GPU billing. Delete the pod afterwards to end disk billing.)
#
# Needs ~/.kaggle/credentials.json (copied up by the launcher, never stored in the repo).
set -uo pipefail
cd "$(dirname "$0")/../.."
REPO=$(pwd)
mkdir -p /workspace/logs
LOG=/workspace/logs/pod_run.log
exec > >(tee -a "$LOG") 2>&1

stop_pod() {
  echo "[$(date +%T)] run.sh exiting"
  if [ "${KEEP_POD:-0}" != "1" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "[$(date +%T)] stopping pod $RUNPOD_POD_ID"
    runpodctl stop pod "$RUNPOD_POD_ID" || runpodctl pod stop "$RUNPOD_POD_ID" || true
  fi
}
trap stop_pod EXIT
( sleep $(( ${HARD_LIMIT_MIN:-200} * 60 )); echo "[$(date +%T)] HARD LIMIT ${HARD_LIMIT_MIN:-200} min reached"; kill -TERM $$ ) &

echo "[$(date +%T)] GPU:"; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
echo "[$(date +%T)] CPUs: $(nproc), RAM: $(free -g | awk '/Mem/{print $2}') GB"

# Fail fast on a host whose GPU PyTorch cannot reach (seen 2026-10-02: nvidia-smi
# fine, torch "CUDA unknown error") -- before any download or training is paid for.
python -c "import sys, torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok); sys.exit(0 if ok else 3)"   || { echo "[$(date +%T)] PyTorch cannot use the GPU on this host: aborting"; exit 3; }
# Runpod's torch images use the system Python (PEP 668), hence --break-system-packages.
python -m pip install -q --break-system-packages pyyaml scikit-image scikit-learn pillow 2>&1 | tail -2
command -v unzip >/dev/null || { apt-get update -qq && apt-get install -y -qq unzip >/dev/null; }

# ---------------------------------------------------------------- data
TOKEN=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.kaggle/credentials.json')))['access_token'])")
fetch() {  # fetch <kaggle owner/slug> <zip path>
  [ -s "$2" ] && return 0
  echo "[$(date +%T)] downloading $1"
  curl -sSfL --retry 5 -H "Authorization: Bearer $TOKEN" -o "$2" "https://www.kaggle.com/api/v1/datasets/download/$1"
}
mkdir -p /workspace/dl data/raw data/external
if [ ! -d data/raw/train/class_0 ]; then
  fetch seraj77/her2-ihc-40x-patch-train /workspace/dl/her2_train.zip && \
  fetch seraj77/her2-ihc-40x-patch-test /workspace/dl/her2_test.zip && \
  mkdir -p data/raw/train data/raw/test && \
  unzip -q -o /workspace/dl/her2_train.zip -d data/raw/train && \
  unzip -q -o /workspace/dl/her2_test.zip -d data/raw/test || { echo "HER2_IHC_40X download failed"; exit 1; }
fi
if [ ! -d data/external/bci_full/IHC/test ]; then
  fetch aasimist/breast-cancer-immunohistochemistry-bci-dataset /workspace/dl/bci.zip && \
  mkdir -p /workspace/dl/bci && unzip -q -o /workspace/dl/bci.zip 'BCI_dataset/IHC/*' -d /workspace/dl/bci && \
  mkdir -p data/external/bci_full && mv /workspace/dl/bci/BCI_dataset/IHC data/external/bci_full/IHC || { echo "BCI download failed"; exit 1; }
fi
echo "[$(date +%T)] data: $(find data/raw -type f | wc -l) HER2_IHC_40X files, BCI train $(ls data/external/bci_full/IHC/train | wc -l), test $(ls data/external/bci_full/IHC/test | wc -l)"
rm -f /workspace/dl/*.zip   # free container disk

# ---------------------------------------------------------------- runs
first=1
for CFG in "$@"; do
  NAME=$(python -c "import sys;sys.path.insert(0,'scripts');from train_v2 import load_config;print(load_config('$CFG')['run_name'])")
  echo "[$(date +%T)] ===== $CFG ($NAME) ====="
  if python -c "import sys;sys.path.insert(0,'scripts');from train_v2 import load_config;sys.exit(0 if ('adapt' in load_config('$CFG') or 'fewshot' in load_config('$CFG')) else 1)"; then
    SCRIPT=scripts/adapt_v2.py; python -c "import sys;sys.path.insert(0,'scripts');from train_v2 import load_config;sys.exit(0 if 'fewshot' in load_config('$CFG') else 1)" && SCRIPT=scripts/fewshot_v2.py
    python $SCRIPT --config "$CFG" || echo "[$(date +%T)] $NAME FAILED (exit $?)"
    tar -czf "/workspace/results_$NAME.tgz" --exclude=adapted.pt -C artifacts/v2 "$NAME" /workspace/logs 2>/dev/null
    echo "[$(date +%T)] packaged /workspace/results_$NAME.tgz ($(du -h /workspace/results_$NAME.tgz | cut -f1))"
    first=0
    continue
  fi
  python scripts/train_v2.py --config "$CFG" --eval || echo "[$(date +%T)] $NAME FAILED (exit $?)"
  RATE=$(python -c "
import json,sys
try: h=json.load(open('artifacts/v2/$NAME/history.json')); print(int(max(r['epoch_tiles_per_s'] for r in h)))
except Exception: print(0)")
  echo "[$(date +%T)] $NAME training throughput: $RATE tiles/s"
  tar -czf "/workspace/results_$NAME.tgz" --exclude=last.pt -C artifacts/v2 "$NAME" /workspace/logs 2>/dev/null
  echo "[$(date +%T)] packaged /workspace/results_$NAME.tgz ($(du -h /workspace/results_$NAME.tgz | cut -f1))"
  if [ $first = 1 ] && [ "$RATE" -lt "${MIN_TILES_PER_S:-40}" ] && [ $# -gt 1 ]; then
    echo "[$(date +%T)] throughput $RATE < ${MIN_TILES_PER_S:-40} tiles/s: skipping remaining runs to save budget"
    break
  fi
  first=0
done
echo "[$(date +%T)] ALL DONE"
# Give the launcher a window to copy results before the pod stops itself.
sleep "${RESULT_GRACE_SEC:-600}"
