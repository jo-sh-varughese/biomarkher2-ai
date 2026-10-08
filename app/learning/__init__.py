"""Continual learning from confirmed cases and annotations, under human control.

Every analysed field or slide is stored with the model's tile embeddings
(store.py). When a pathologist signs a review, its score becomes that case's
label; region annotations label the tiles inside them. From these the
learner trains a CANDIDATE version of the model's final stage -- the
attention pooling and the score head -- on frozen image features, mixed with
replay cases from the training site so earlier knowledge is kept (head.py).

Nothing changes live predictions by itself: each candidate is evaluated
against pre-registered gates -- no loss on a LOCKED reference set, a real
gain on the site's own confirmed cases (cross-validated) -- and goes live
only when an administrator activates it (registry.py, service.py). Every
version is kept, every prediction records the version that made it, and
rollback is one action. See docs/LEARNING.md.
"""
