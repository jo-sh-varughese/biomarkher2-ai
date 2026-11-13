"""Assemble the SDC handover package from the repo, the built documents and the deployment bundle.

    python docs/handover/make_package.py            (after build.py and deploy/sdc/make_offline_bundle.sh)

Output: dist/BioMarkHER2_SDC_Handover_<date>/ with the folder layout in 00_Handover_Index.md and a SHA256SUMS.txt.
"""
from __future__ import annotations

import fnmatch
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "sdc-2026.11.11"
OUT = ROOT / "dist" / "BioMarkHER2_SDC_Handover_2026-11-11"
DOCS = ROOT / "dist" / "handover_docs"
BUNDLE = ROOT / "dist" / "sdc_bundle"

# What the source code is: everything needed to build, run, test, retrain and document the system.
SOURCE_DIRS = ["app", "wsi", "models", "preprocessing", "training", "evaluation", "configs", "scripts", "tests",
               "ui", "docs", "deploy", "reports", ".github"]
SOURCE_FILES = ["Dockerfile", "docker-compose.yml", ".dockerignore", ".gitignore", ".gitattributes", "requirements.txt",
                "pyproject.toml", "pytest.ini", "README.md", "CONTRIBUTING.md", "IMPLEMENTATION_NOTES.md",
                "PROJECT_PLAN.md", "PHASE2.md", "PHASE4.md", "PHASE5.md", "PHASE5_8EPOCHS.md",
                "PHASE5_CLASS_WEIGHTS.md", "PHASE5_MEMBRANE_COMPLETENESS.md", "PHASE5_ORDINAL.md",
                "PHASE5_THRESHOLD_SENSITIVITY.md", "PHASE6_NOTES.md", "biomark.bat", "start.bat", "stop.bat",
                "serve.bat", "start_server.bat"]
# Build output, caches, personal images and third-party pages are not source.
EXCLUDE = ["*/__pycache__/*", "*.pyc", "ui/node_modules/*", "ui/dist/*", "ui/WhatsApp Image*",
           "ui/www-pathai-com-*", "ui/.netlify/*", "docs/note25sep/*", "*.log", "*/.pytest_cache/*"]

# Model evaluation outputs (metrics and confusion matrices). SDC asked for the models, not the datasets, so no
# images, split lists or per-image predictions are included.
MODEL_EVALUATION = {
    "evaluation/prescore_run_b_eval.json": "artifacts/v2/run_b/eval.json",
    "evaluation/stain_map_val_metrics.json": "artifacts/phase2_unet_8epochs/val_metrics_best.json",
    "evaluation/stain_map_val_confusion.csv": "artifacts/phase2_unet_8epochs/val_confusion_best.csv",
    "evaluation/cell_engine_calibration.json": "configs/cell_params.json",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_files() -> list[Path]:
    files = [ROOT / f for f in SOURCE_FILES if (ROOT / f).is_file()]
    for d in SOURCE_DIRS:
        files += [p for p in (ROOT / d).rglob("*") if p.is_file()]
    keep = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if not any(fnmatch.fnmatch(rel, pat) for pat in EXCLUDE):
            keep.append(p)
    return sorted(set(keep))


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def main() -> int:
    for need in (DOCS, BUNDLE / "images.tar.gz"):
        if not need.exists():
            sys.exit(f"missing {need}: run docs/handover/build.py and deploy/sdc/make_offline_bundle.sh first")
    # Empty the folder rather than delete it: on Windows an open shell or Explorer window there locks the folder itself.
    OUT.mkdir(parents=True, exist_ok=True)
    for child in OUT.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    d = {k: OUT / k for k in ("01_Source_Code", "02_Models", "03_Technical_Documentation", "04_Deployment",
                              "05_Manuals", "06_Knowledge_Transfer")}
    for p in d.values():
        p.mkdir(parents=True)

    # 01 source
    files = source_files()
    zpath = d["01_Source_Code"] / f"biomarkher2-{RELEASE}-source.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, f"biomarkher2-{RELEASE}/{p.relative_to(ROOT).as_posix()}")
    head = git("rev-parse", "HEAD")
    # Only the shipped files decide whether the zip matches the commit (other untracked files in the repo do not).
    shipped = {p.relative_to(ROOT).as_posix() for p in files}
    changed = set(git("diff", "--name-only", "HEAD").splitlines()) | set(git("ls-files", "--others", "--exclude-standard").splitlines())
    status = "\n".join(sorted(shipped & changed))
    with open(d["01_Source_Code"] / "SOURCE_MANIFEST.txt", "w", encoding="utf-8", newline="\n") as m:
        m.write(f"BioMarkHER2 source, release {RELEASE}\n")
        m.write(f"git commit: {head}{'  (plus uncommitted changes, see below)' if status else ''}\n")
        m.write(f"files: {len(files)}\n\n")
        for p in files:
            m.write(f"{sha256(p)}  {p.relative_to(ROOT).as_posix()}\n")
        if status:
            m.write("\nWorking-tree changes relative to the commit:\n" + status + "\n")
    shutil.copy2(ROOT / "requirements.txt", d["01_Source_Code"])
    shutil.copy2(ROOT / "ui" / "package-lock.json", d["01_Source_Code"])

    # 02 models
    shutil.copy2(BUNDLE / "biomark_models.tgz", d["02_Models"])
    shutil.copy2(ROOT / "artifacts" / "MODELS.sha256", d["02_Models"])

    # 02 models: evaluation outputs
    for dest, src in MODEL_EVALUATION.items():
        target = d["02_Models"] / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, target)

    # documents
    placement = {"00": OUT, "01": d["03_Technical_Documentation"], "02": d["04_Deployment"], "03": d["05_Manuals"],
                 "04": d["05_Manuals"], "05": d["06_Knowledge_Transfer"]}
    for f in sorted(DOCS.glob("[0-9][0-9]_*")):
        if f.suffix in (".pdf", ".docx"):
            shutil.copy2(f, placement[f.name[:2]])

    # 04 deployment bundle (images + models + scripts)
    shutil.copytree(BUNDLE, d["04_Deployment"] / "sdc_bundle")

    # checksums of everything
    with open(OUT / "SHA256SUMS.txt", "w", encoding="utf-8", newline="\n") as s:
        for p in sorted(OUT.rglob("*")):
            if p.is_file() and p.name != "SHA256SUMS.txt":
                s.write(f"{sha256(p)}  {p.relative_to(OUT).as_posix()}\n")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"{OUT}  ({total / 1e9:.2f} GB, {len(files)} source files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
