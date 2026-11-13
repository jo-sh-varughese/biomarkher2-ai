"""Pick demo images that the live pipeline handles correctly: held-out patches of grade 0, 1+ and 2+
that get the right AI pre-score with a confident single-grade set, and false-positive inputs that the
field-quality gate refuses. Run from the repository root: python scripts/pick_demo_images.py"""
import json, random, sys, shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.server import build_argparser, build_site_policy  # noqa: E402
from app.analysis import Analyzer  # noqa: E402

OUT = Path("demo_images")
OUT.mkdir(exist_ok=True)
args = build_argparser().parse_args([])
policy = build_site_policy(args)
an = Analyzer(args.run, args.config, args.preprocessing, args.conformal_alpha,
              prescore_checkpoint=args.prescore_run, site_policy=policy)
print("site gate:", policy["status"], flush=True)

def run(rgb, name):
    r = an.analyze(rgb, patch_id=name).to_dict()
    q = r.get("quality") or {}
    blk = r.get("ai_prescore") or {}
    p = blk.get("prescore") or {}
    ps = p.get("prediction_set") or {}
    ce = r.get("cell_evidence") or {}
    return {"assessable": q.get("assessable"), "reasons": [(x.get("level"), x.get("text")) for x in q.get("reasons", [])][:3],
            "grade": p.get("category"), "conf": p.get("confidence"), "set": ps.get("labels") or ps.get("set") or ps,
            "cells": ce.get("field_category"), "n_cells": (ce.get("summary") or {}).get("n_cells")}

def load(path):
    return np.asarray(Image.open(path).convert("RGB"))

results = {}
random.seed(11)
for cls in ["class_0", "class_1+", "class_2+"]:
    files = sorted(Path("data/raw/test", cls).glob("*.png")) + sorted(Path("data/raw/test", cls).glob("*.jpg"))
    tag = "her2-" + cls.split("_")[1] + "-score_test"
    files = [f for f in files if f.name.startswith(tag)]   # held-out, filename agrees with the folder
    for f in random.sample(files, min(10, len(files))):
        res = run(load(f), f.name)
        results[str(f)] = res
        print(cls, f.name, json.dumps(res, default=str)[:400], flush=True)

# false-positive candidates built from a held-out 3+ patch
src = sorted(Path("data/raw/test/class_3+").glob("*"))[0]
base = Image.open(src).convert("RGB")
fp = {
    "fp_greyscale_photo": base.convert("L").convert("RGB"),
    "fp_out_of_focus": base.filter(ImageFilter.GaussianBlur(14)),
    "fp_noise": Image.fromarray(np.random.default_rng(3).integers(0, 255, (1024, 1024, 3), dtype=np.uint8)),
}
for name, im in fp.items():
    im.save(OUT / f"{name}.png")
    res = run(np.asarray(im), name)
    results[name] = res
    print(name, json.dumps(res, default=str)[:500], flush=True)
json.dump(results, open(OUT / "_check.json", "w"), indent=1, default=str)
