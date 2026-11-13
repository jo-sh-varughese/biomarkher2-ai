#!/usr/bin/env bash
# Runs ON the Runpod pod. One job: tile embeddings of the replay, reference and BCI sets for the adaptation curve.
#
#   bash scripts/pod/embed.sh
#
# Why a GPU at all: the adaptation curve (scripts/learning_simulation.py) trains only a small head on frozen
# 512-dim tile embeddings, which is seconds of CPU work. The one heavy step is computing those embeddings once
# for every BCI image (3,896 train + 977 test, 1024 px) plus the 800 replay/reference images: hours on a laptop
# CPU, a few minutes on any 16 GB GPU. Nothing is trained on the pod and no patient data is involved (both
# datasets are public).
#
# Cost guards (same spirit as scripts/pod/run.sh):
#   * HARD_LIMIT_MIN (default 45): a watchdog stops the pod after this many minutes no matter what.
#   * The pod is stopped on exit, success or failure, unless KEEP_POD=1. Delete it afterwards to end disk billing.
#
# Needs the checkpoint artifacts/v2/run_a/best.pt and /workspace/data_her2_800.tgz (both scp'd up by the launcher).
set -uo pipefail
cd "$(dirname "$0")/../.."
mkdir -p /workspace/logs
LOG=/workspace/logs/embed.log
exec > >(tee -a "$LOG") 2>&1

stop_pod() {
  echo "[$(date +%T)] embed.sh exiting"
  if [ "${KEEP_POD:-0}" != "1" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
    echo "[$(date +%T)] stopping pod $RUNPOD_POD_ID"
    runpodctl stop pod "$RUNPOD_POD_ID" || runpodctl pod stop "$RUNPOD_POD_ID" || true
  fi
}
trap stop_pod EXIT
( sleep $(( ${HARD_LIMIT_MIN:-45} * 60 )); echo "[$(date +%T)] HARD LIMIT ${HARD_LIMIT_MIN:-45} min reached"; kill -TERM $$ ) &

echo "[$(date +%T)] GPU:"; nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
echo "[$(date +%T)] CPUs: $(nproc), RAM: $(free -g | awk '/Mem/{print $2}') GB"
python -c "import sys, torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, 'cuda', ok); sys.exit(0 if ok else 3)" \
  || { echo "[$(date +%T)] PyTorch cannot reach the GPU on this host: stopping before anything is downloaded"; exit 3; }
python -m pip install -q --break-system-packages pyyaml scikit-image scikit-learn pillow 2>&1 | tail -2
command -v unzip >/dev/null || { apt-get update -qq && apt-get install -y -qq unzip >/dev/null; }
[ -s artifacts/v2/run_a/best.pt ] || { echo "artifacts/v2/run_a/best.pt is missing (scp it up first)"; exit 1; }

# ---------------------------------------------------------------- data
# HER2-IHC-40x: only the 800 replay/reference images are needed; the launcher uploads them (data_her2_800.tgz,
# ~120 MB, same relative paths as data/raw). BCI: the authors' public Google Drive copy (non-commercial research
# licence), fetched with gdown -- no Kaggle account needed.
mkdir -p data/raw data/external /workspace/dl
if [ ! -d data/raw/train/class_0 ] && [ -s /workspace/data_her2_800.tgz ]; then
  tar -xzf /workspace/data_her2_800.tgz --no-same-owner -C . || { echo "HER2 image archive failed to unpack"; exit 1; }
fi
[ -d data/raw/test ] || { echo "HER2 images missing (scp data_her2_800.tgz to /workspace first)"; exit 1; }
if [ ! -d data/external/bci_full/IHC/test ]; then
  python -m pip install -q --break-system-packages gdown 2>&1 | tail -1
  echo "[$(date +%T)] downloading BCI_dataset.zip from Google Drive"
  python -m gdown "${BCI_DRIVE_ID:-1jPPh-rxUaj_bCB58F9mfg9hjY7JjVt3O}" -O /workspace/dl/bci.zip     || { echo "BCI download failed (Drive quota?)"; exit 1; }
  mkdir -p /workspace/dl/bci && unzip -q -o /workspace/dl/bci.zip 'BCI_dataset/IHC/*' -d /workspace/dl/bci &&   mkdir -p data/external/bci_full && mv /workspace/dl/bci/BCI_dataset/IHC data/external/bci_full/IHC || { echo "BCI unzip failed"; exit 1; }
fi
echo "[$(date +%T)] data: BCI train $(ls data/external/bci_full/IHC/train | wc -l), test $(ls data/external/bci_full/IHC/test | wc -l)"
rm -f /workspace/dl/*.zip

# ---------------------------------------------------------------- embeddings
mkdir -p artifacts/learning
python scripts/extract_learning_features.py \
  --checkpoint artifacts/v2/run_a/best.pt --out artifacts/learning/features_run_a.npz \
  --device cuda --batch "${BATCH:-8}" --workers "$(( $(nproc) < 8 ? $(nproc) : 8 ))" --per-class 100 \
  --bci-dirs data/external/bci_full/IHC/train data/external/bci_full/IHC/test \
  || { echo "[$(date +%T)] extraction FAILED"; exit 4; }
cp artifacts/learning/features_run_a.npz /workspace/features_run_a.npz
echo "[$(date +%T)] packaged /workspace/features_run_a.npz ($(du -h /workspace/features_run_a.npz | cut -f1))"
echo "[$(date +%T)] ALL DONE"
# Give the launcher a window to copy the result before the pod stops itself.
sleep "${RESULT_GRACE_SEC:-300}"
