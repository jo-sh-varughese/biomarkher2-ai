"""Render the system pipeline diagram for the full-system paper as a plain
PNG (no TikZ) -- there is no local LaTeX engine on this machine to verify a
TikZ figure compiles, so the diagram is drawn once here with matplotlib
instead, exactly like every other figure in paper/figures/.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(7.2, 4.0))
ax.set_xlim(0, 10)
ax.set_ylim(0, 6)
ax.axis("off")

def box(x, y, w, h, text, color="#e8eef0", edge="#2f3e46"):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.08",
                        linewidth=1.3, edgecolor=edge, facecolor=color)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8.7,
             color="#1a1a1a")

def arrow(p0, p1, color="#2f3e46", style="-|>"):
    a = FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=12,
                         linewidth=1.2, color=color, shrinkA=2, shrinkB=2)
    ax.add_patch(a)

# Row 1: main left-to-right pipeline
box(0.2, 4.6, 1.9, 1.0, "Phase 1\nPreprocessing\n(stains, tissue,\nDAB baseline)")
box(2.5, 4.6, 1.9, 1.0, "Phase 2\nWeak-supervision\ntraining\n(pseudo-labels)")
box(4.8, 4.6, 1.9, 1.0, "Phase 5\nArchitecture\ncomparison")
box(7.1, 4.6, 2.6, 1.0, "ResNet18-UNet\n(adopted; SegFormer\nremoved)", color="#dff0ea")

arrow((2.1, 5.1), (2.5, 5.1))
arrow((4.4, 5.1), (4.8, 5.1))
arrow((6.7, 5.1), (7.1, 5.1))

# Row 2: evaluation + app
box(0.2, 2.6, 3.0, 1.1, "Phase 4\nEvaluation\n(conformal prediction,\nstain variation, CAP/ASCO)")
box(3.7, 2.6, 3.0, 1.1, "Review-viewer app\n(model vs. classical\nbaseline, side by side)")
box(7.1, 2.6, 2.6, 1.1, "Human review\n(pathologist confirms\na score)", color="#f3e6d3")

arrow((8.4, 4.6), (8.4, 3.7))
arrow((3.2, 3.15), (3.7, 3.15))
arrow((6.7, 3.15), (7.1, 3.15))

# Row 3: feedback loop
box(3.7, 0.6, 3.0, 1.1, "reviews.jsonl\n(pathologist-confirmed\nscores)")
arrow((8.4, 2.6), (8.4, 1.15))
arrow((8.4, 1.15), (6.7, 1.15))
arrow((3.7, 1.15), (1.7, 1.15))
arrow((1.7, 1.15), (1.7, 2.6))

ax.text(0.2, 0.15,
        "Solid arrows: data flow.  Feedback loop: confirmed reviews become\n"
        "Phase 4's expert-agreement evaluation input (Cohen's kappa).",
        fontsize=7.3, style="italic", color="#333333")

fig.tight_layout()
fig.savefig("pipeline_diagram.png", dpi=170)
print("wrote pipeline_diagram.png")
