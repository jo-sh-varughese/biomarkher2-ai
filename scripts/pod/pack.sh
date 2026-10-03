#!/usr/bin/env bash
# Runs LOCALLY. Packs just the code and frozen inputs the pod needs (no data,
# no artifacts) into dist/her2_v2_code.tgz for scp.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p dist
tar -czf dist/her2_v2_code.tgz \
  --exclude='__pycache__' --exclude='*.pyc' \
  models training preprocessing evaluation wsi \
  scripts/train_v2.py scripts/eval_v2.py scripts/adapt_v2.py scripts/fewshot_v2.py scripts/site_fingerprint.py scripts/train_tumour.py scripts/pod \
  configs
ls -la dist/her2_v2_code.tgz
