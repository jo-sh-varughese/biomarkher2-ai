"""Phase 4 -- evaluation tools that sit on top of a trained Phase 2 checkpoint.

Nothing here trains a model or changes what Phase 2 produces. This package
answers three questions Phase 2 deliberately left open:

* How much does the estimated stain actually vary across the dataset's
  provenance groups? (:mod:`evaluation.stain_variation`, :mod:`evaluation.stain_shift`)
* How confident is the model, pixel by pixel, and how should that confidence
  be discounted when a test patch's stain looks unlike the calibration set's?
  (:mod:`evaluation.conformal`)
* What would the model's output say under ASCO/CAP scoring, and how well
  does that agree with a reference labelling -- run today only against the
  dataset's own labels, ready to run against real expert annotation the day
  it exists? (:mod:`evaluation.cap_mapping`)

See PHASE4.md for how these compose into a run, and why the CAP/ASCO mapping
is not, and must not become, a field in the live viewer's API.
"""
