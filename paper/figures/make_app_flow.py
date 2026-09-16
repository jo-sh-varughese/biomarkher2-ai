"""Review-viewer request-flow diagram for the full-system paper -- the same
flow app/README.md and the project README document, redrawn as a plain
flowchart (no mermaid/TikZ dependency) since this machine has no local
LaTeX engine to verify a TikZ version against.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(4.6, 7.6))
ax.set_xlim(0, 6)
ax.set_ylim(0, 15.2)
ax.axis("off")

def box(y, text, h=1.0, color="#e3e9ea", w=5.4, x=0.3, fontsize=8.0):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.09",
                        linewidth=1.1, edgecolor="#2f3e46", facecolor=color)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize)
    return y

def arrow(y0, y1, x=3.0, label=None, color="#2f3e46"):
    a = FancyArrowPatch((x, y0), (x, y1), arrowstyle="-|>", mutation_scale=11,
                         linewidth=1.2, color=color, shrinkA=1, shrinkB=1)
    ax.add_patch(a)
    if label:
        ax.text(x + 0.15, (y0 + y1) / 2, label, fontsize=6.8, va="center",
                color="#555555", style="italic")

steps = [
    (13.9, "Pathologist opens the review-viewer\n(browser, app/static)", "#f2f2f2"),
    (12.55, "GET /api/context\nsample list, class legend, caveats", "#e3e9ea"),
    (11.2, "Pick a sample patch, or upload an image", "#f2f2f2"),
    (9.85, "POST /api/analyze", "#e3e9ea"),
    (8.2, "Analyzer: classical DAB baseline\n+ tiled U-Net prediction, same tissue mask", "#dce6e8"),
    (6.85, "JSON response: area % per class,\nmodel & baseline side by side -- no score field", "#e3e9ea"),
    (5.5, "Four panels + table rendered together\n(baseline never hidden behind a toggle)", "#f2f2f2"),
    (4.15, "Pathologist reviews, picks a score,\nsubmits the review form explicitly", "#f3e6d3"),
    (2.8, "POST /api/review", "#e3e9ea"),
    (1.45, "reviews.jsonl\n{reviewer, score, measurements, timestamp}", "#dfeee7"),
    (0.1, "optional: POST /api/report -> PDF\n(same payload, same never-a-score guarantee)", "#f2f2f2"),
]

for y, text, color in steps:
    box(y, text, color=color)

ys = [s[0] for s in steps]
for i in range(len(ys) - 1):
    arrow(ys[i], ys[i + 1] + 1.0)

fig.tight_layout()
fig.savefig("app_flow.png", dpi=170)
print("wrote app_flow.png")
