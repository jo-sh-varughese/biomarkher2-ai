# BioMarkHER2 — IEEE conference paper drafts

Two self-contained LaTeX papers, both `\documentclass[conference]{IEEEtran}`
using the standard IEEE conference template structure, **compiled to PDF**
(`focused-methods/main.pdf`, 11 pages; `full-system/main.pdf`, 10 pages),
built from this repo's actual results (Phase 1–5, see `../PHASE2.md`,
`../PHASE4.md`, `../PHASE5.md`, `../IMPLEMENTATION_NOTES.md`) — no invented
numbers, figures, or citations.

```
paper/
  focused-methods/main.tex   -- "focused methods" paper source
  focused-methods/main.pdf   -- compiled PDF (11 pages, 7 figures, 5 tables, 19 refs)
  full-system/main.tex       -- "full system" paper source
  full-system/main.pdf       -- compiled PDF (10 pages, 9 figures, 3 tables, 21 refs)
  figures/                   -- shared figures, referenced by both papers
    make_*.py                -- regenerates the corresponding diagram/chart
```

## What's in each paper

Both papers now carry, beyond the original draft:

- **Formal problem statement.** A notation section (`focused-methods`,
  Section IV-A) states the weak-supervision estimator explicitly
  (Eq. 1) and states the pseudo-label circularity as a proven Remark, not
  just a caveat in prose. `full-system` states the "assistive, never
  autonomous" rule as a formal functional boundary ($g_\theta$ never
  implements $h$, Section III-A) instead of only as a sentence.
- **A stated coverage proposition** for the conformal predictor
  (`focused-methods`, Proposition 1), connecting the empirical
  miscoverage-tracks-$\alpha$ result back to the theorem it instantiates.
- **A validity-threat analysis** organized by the standard
  construct/internal/external/statistical-conclusion taxonomy, replacing
  the earlier flat "Limitations" bullet list.
- **A Broader Impact and Ethical Considerations section** in both papers —
  automation bias, dataset representativeness, and equity of access
  (CPU-only as a deliberate access decision, not just a constraint).
- **Real, code-derived figures**, several generated fresh for this
  revision by running this repo's actual `preprocessing/` functions
  against real HER2_IHC_40X patches (not illustrations):
  stain deconvolution (RGB → haematoxylin → DAB) on a real 3+ patch,
  and the Otsu-vs-optical-density tissue-detection failure mode on a
  real faint patch (34.9% vs. 51.9% tissue coverage, measured, not
  assumed). Plus a from-code ResNet18-UNet architecture diagram (channel
  counts and strides read directly from `models/unet_seg.py`'s
  `forward()`), a compute-vs-accuracy trade-off plot, and a pixel-level
  class-balance chart.
- **7 additional, independently verified literature references** (via
  live search, not recalled from memory) grounding the paper in
  2019–2026 work: a computational-pathology survey (Bera et al., *Nat.
  Rev. Clin. Oncol.* 2019), two recent automated HER2-scoring CNNs
  (Selcuk et al. 2024; Mridha et al. 2022), a direct precedent for
  patch-label weak supervision in histopathology (Han et al. 2021), a
  stain-normalization CycleGAN (Hetz et al., *Med. Image Anal.* 2024),
  and two 2025/2026 conformal-prediction-for-segmentation papers
  (Mossina & Friedrich, MICCAI 2025; Borden et al., *J. Appl. Clin. Med.
  Phys.* 2026) that the Related Work section explicitly differentiates
  this paper's contribution from.

Both still report the same honest caveats this repo enforces everywhere
else: pseudo-label supervision (no pathologist pixel annotations exist),
no verified slide-level split, a single-source dataset (stain-shift
weighting validated on synthetic shift only), and a smoke-scale conformal
evaluation. The added rigor is additional structure and grounding, not a
softening of any caveat.

## The two papers

- **`focused-methods/`** — *DAB-Guided Weak Supervision and
  Stain-Shift-Weighted Conformal Prediction for HER2 IHC Intensity
  Segmentation*. Foregrounds the two novel contributions: the RGB+DAB
  4-channel U-Net input, and generalizing binary/image-level conformal
  prediction (Pintawong et al., 2025) to pixel-level, 5-class segmentation.
- **`full-system/`** — *BioMarkHER2: A Pathologist-in-the-Loop System for
  Quantitative HER2 IHC Pre-Scoring Under Weak Supervision and CPU-Only
  Compute*. Covers the whole pipeline end to end, including the
  review-viewer app and its test-enforced "never a score" rule, now
  stated as a formal functional invariant.

## Figures and diagrams

| Figure | Source | Used in |
|---|---|---|
| System pipeline diagram | drawn from the phase structure in `PROJECT_PLAN.md` | full-system |
| Dataset class distribution | real test-split counts (758/538/226/678) | both |
| Stain deconvolution (RGB→H→DAB) | run live via `preprocessing/stains.py` on a real patch | both |
| Tissue detection comparison (Otsu vs. OD) | run live via `preprocessing/tissue.py` on a real patch | both |
| Pixel-level class balance | `PHASE2.md`'s training-target pixel table | both |
| ResNet18-UNet architecture | drawn from `models/unet_seg.py`'s actual `forward()` | both |
| SegFormer vs. U-Net comparison chart | `PHASE5.md`'s reported numbers | both |
| Compute-vs-accuracy trade-off | `PHASE5.md`'s measured per-image timings | both |
| Training curves / confusion matrix / per-class bars | regenerated from `artifacts/phase2_unet` | both |
| Qualitative prediction preview | regenerated via `scripts/predict_preview.py` | both |
| Conformal prediction curves | regenerated via `scripts/evaluate_conformal.py` | focused-methods |
| Stain-variation scatter | `artifacts/phase4/stain_variation.png` | full-system |
| Review-viewer request-flow diagram | drawn from `app/server.py` / `app/README.md`'s documented flow | full-system |

No diagram uses TikZ — this machine has no local LaTeX engine to verify
TikZ syntax against, so every diagram is a pre-rendered PNG built with
matplotlib (`figures/make_*.py`), each script documenting exactly which
real numbers or code it drew from.

## What's still a placeholder

Author block is filled in with the real team (J. S. Varughese, Nadeema
Jahan, Aiswarya M S, Rishika Pratap Jadgale, and project guide Dr. Jesna
Mohan — all Dept. of CSE, Mar Baselios College of Engineering and
Technology, Thiruvananthapuram), laid out as 2/2/1 rows (via a
`\linebreakand` macro) so Dr. Mohan's name is centered on its own row
rather than stranded to one side. Only the funding line and Acknowledgment
section remain placeholders ("withheld pending submission") since no
funding source or additional acknowledgee was specified.

**Known LaTeX gotcha, already avoided here:** IEEEtran's title/author
processing macros crash (`! Missing number, treated as zero.`) on a
literal `[` or `]` character inside `\author{...}` — confirmed by
isolating it during this draft's compilation. Don't wrap author names in
square brackets.

## Compiling

Standard `IEEEtran` two-column conference format, no exotic packages.
Both PDFs here are compiled with a real `pdflatex` (TeX Live 2026, via a
portable TinyTeX install fetched for this session — no system-wide LaTeX
was on this machine). An earlier draft was compiled with
[Tectonic](https://tectonic-typesetting.github.io/) (a self-contained
XeTeX-family engine) as a stopgap; that engine could not correctly resolve
IEEEtran's classic bold-title/bold-"Abstract"/small-caps-section-heads
font shapes (they're defined for 8-bit OT1/T1 encoding, and XeTeX-family
engines default to Unicode "TU" encoding instead), so the visual output
was silently degraded — plain-weight headings instead of small caps, etc.
Real `pdflatex` doesn't have that problem, which is what both PDFs here
now use. Any real TeX distribution with the `IEEEtran` class (TeX Live,
MiKTeX, Overleaf all ship it) will compile either paper identically:

```
pdflatex main.tex
pdflatex main.tex   # twice, to resolve references
```

or just upload the relevant subfolder (including `../figures/`) to
Overleaf as a project.

## Citations

19 references (focused-methods) / 21 references (full-system). The base
paper this project's conformal prediction method generalizes is cited
exactly as named in `evaluation/conformal.py`'s own module docstring:
Pintawong et al. (2025), "Conformal Prediction for Uncertainty
Quantification and Reliable HER2 Status Classification in Breast Cancer
IHC Images," IEEE Access. The original method citations (Ruifrok &
Johnston, Wolff et al./ASCO-CAP, Ronneberger et al./U-Net, He et
al./ResNet, Xie et al./SegFormer, Lin et al./focal loss,
Vovk-Gammerman-Shafer, Sadinle-Lei-Wasserman, Tibshirani et al., Macenko
et al., Reinhard et al., Otsu, Cohen) are the standard references already
named in the corresponding source modules' own docstrings. The 7
literature-review additions (Bera et al. 2019; Selcuk et al. 2024; Mridha
et al. 2022; Han et al. 2021; Hetz et al. 2024; Mossina & Friedrich 2025;
Borden et al. 2026) were found and their author lists/venues verified via
live web search during this revision — not recalled from memory — to
avoid citing anything that couldn't be checked.
