"""Does the continual learner actually learn? Simulated onboarding of a new hospital.

    python scripts/learning_simulation.py --features artifacts/learning/features_run_a.npz --checkpoint artifacts/v2/run_a/best.pt

Run A never saw BCI, so BCI plays a new hospital. 200 BCI images are a fixed,
untouched test set; the other images arrive as "signed cases" in random
order. After k of them (k = 25, 50, 100, 150, all) a candidate head is trained
exactly as the live system trains it (app/learning/head.train, with replay
from the training site), and measured on the BCI test set and on the LOCKED
training-site reference set. The live system's gates (configs/learning.yaml)
are applied to every candidate, so the table also says when the system would
have offered an update. Ten random orders per k.

Writes artifacts/learning/simulation_<run>.json and .md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
import yaml  # noqa: E402

from app.learning import head as H  # noqa: E402
from training.v2_engine import load_model  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", required=True)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--test", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261003)
    args = ap.parse_args()
    cfg = yaml.safe_load(open(ROOT / "configs/learning.yaml", encoding="utf-8"))
    tr, g = cfg["training"], cfg["gates"]
    kw = {k: tr[k] for k in ("epochs", "lr", "anchor", "tile_weight")}
    z = np.load(ROOT / args.features, allow_pickle=True)

    def cases(name):
        return [H.Case(emb=e.astype(np.float32), label=int(y), case_id=str(i))
                for e, y, i in zip(z[f"{name}_emb"], z[f"{name}_label"], z[f"{name}_id"])]

    replay, reference, bci = cases("replay"), cases("reference"), cases("bci")
    model = load_model(ROOT / args.checkpoint, torch.device("cpu")).float().eval()
    base = H.Head.from_model(model)
    rng = np.random.default_rng(args.seed)
    labels = np.array([c.label for c in bci])
    test_idx = np.concatenate([rng.permutation(np.nonzero(labels == k)[0])[: args.test // 4] for k in range(4)])
    pool_idx = np.setdiff1d(np.arange(len(bci)), test_idx)
    test = [bci[i] for i in test_idx]
    base_test, base_ref = H.metrics(base, test), H.metrics(base, reference)
    print(f"base: BCI test {base_test['accuracy']:.3f} / QWK {base_test['qwk']:.3f}; reference {base_ref['accuracy']:.3f}", flush=True)
    ks = [k for k in (25, 50, 100, 150) if k < len(pool_idx)] + [len(pool_idx)]
    rows = []
    for k in ks:
        accs, qwks, refs, ref_qwks, passed = [], [], [], [], []
        for r in range(args.repeats):
            order = np.random.default_rng(args.seed + r).permutation(pool_idx)
            local = [bci[i] for i in order[:k]]
            cand = H.train(base, local, replay, seed=r, **kw)
            mt, mr = H.metrics(cand, test), H.metrics(cand, reference)
            accs.append(mt["accuracy"]); qwks.append(mt["qwk"]); refs.append(mr["accuracy"]); ref_qwks.append(mr["qwk"])
            by_grade = np.bincount([c.label for c in local], minlength=4)
            gate = False
            if k >= g["min_labelled_cases"] and by_grade.min() >= g["min_per_grade"]:
                cv = H.cross_validate(base, local, replay, folds=tr["folds"], seed=r, **kw)
                gate = (cv.get("enough") and mr["accuracy"] >= base_ref["accuracy"] - g["reference_max_accuracy_drop"]
                        and mr["qwk"] >= base_ref["qwk"] - g["reference_max_qwk_drop"]
                        and cv["candidate"]["accuracy"] >= cv["current"]["accuracy"] + g["local_min_accuracy_gain"]
                        and cv["candidate"]["big_error_rate"] <= cv["current"]["big_error_rate"] + g["local_max_big_error_increase"])
            passed.append(bool(gate))
        row = {"k": int(k), "bci_accuracy_mean": round(float(np.mean(accs)), 4), "bci_accuracy_min": round(float(np.min(accs)), 4),
               "bci_accuracy_max": round(float(np.max(accs)), 4), "bci_qwk_mean": round(float(np.mean(qwks)), 4),
               "reference_accuracy_mean": round(float(np.mean(refs)), 4), "reference_qwk_mean": round(float(np.mean(ref_qwks)), 4),
               "gate_pass_rate": round(float(np.mean(passed)), 2)}
        rows.append(row)
        print(row, flush=True)
    out = {"features": args.features, "checkpoint": args.checkpoint, "n_test": len(test), "n_pool": int(len(pool_idx)),
           "repeats": args.repeats, "base": {"bci": base_test, "reference": base_ref}, "curve": rows, "training": kw, "gates": g}
    name = Path(args.checkpoint).parent.name
    (ROOT / f"artifacts/learning/simulation_{name}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    md = [f"# Learning simulation -- {name} (BCI as a new hospital)", "",
          f"Fixed BCI test set: {len(test)} images; cases learned from: up to {len(pool_idx)}; {args.repeats} random orders.",
          f"Before learning: BCI accuracy {base_test['accuracy']:.1%}, QWK {base_test['qwk']:.3f}; "
          f"reference accuracy {base_ref['accuracy']:.1%}.", "",
          "| confirmed cases | BCI accuracy (mean, min-max) | BCI QWK | reference accuracy | gates passed |",
          "|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['k']} | {r['bci_accuracy_mean']:.1%} ({r['bci_accuracy_min']:.1%}-{r['bci_accuracy_max']:.1%}) | "
                  f"{r['bci_qwk_mean']:.3f} | {r['reference_accuracy_mean']:.1%} | {r['gate_pass_rate']:.0%} |")
    (ROOT / f"artifacts/learning/simulation_{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
