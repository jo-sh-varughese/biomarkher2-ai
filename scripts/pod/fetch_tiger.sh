#!/usr/bin/env bash
# Downloads the TIGER WSIROIS tissue-cells ROIs (images + masks, ~460 MB) from
# the public tiger-training S3 bucket (AWS Open Data, CC BY-NC 4.0) into
# data/external/tiger/tissue-cells, with the same sanitized file names used
# locally (brackets, commas and spaces replaced). Safe to re-run.
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT=data/external/tiger/tissue-cells
one() {
  key="$1"; rel="${key#wsirois/roi-level-annotations/tissue-cells/}"
  safe=$(printf %s "$rel" | sed 's/\[/_/g; s/\]//g; s/, /_/g; s/,/_/g; s/ /_/g')
  out="$OUT/$safe"
  [ -s "$out" ] && return 0
  mkdir -p "$(dirname "$out")"
  enc=$(printf %s "$key" | sed 's/ /%20/g; s/\[/%5B/g; s/\]/%5D/g; s/,/%2C/g')
  curl -sf -m 300 --retry 3 -o "$out" "https://tiger-training.s3.amazonaws.com/$enc" || { echo "FAIL $key"; rm -f "$out"; }
}
export -f one; export OUT
tr -d '\r' < configs/tiger_tissue_cells_keys.txt | grep -E '/(images|masks)/' | xargs -d '\n' -P 16 -I{} bash -c 'one "$@"' _ {}
echo "TIGER: $(ls $OUT/images | wc -l) images, $(ls $OUT/masks | wc -l) masks"
