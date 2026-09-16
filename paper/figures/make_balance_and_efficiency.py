"""Two more real-numbers charts for the paper:
1. Pixel-level class balance over the 792 fit tiles (PHASE2.md's own table).
2. Compute-vs-accuracy tradeoff, SegFormer-B0 vs. ResNet18-UNet (PHASE5.md's
   measured per-image cost and PHASE2/5's tissue mean IoU numbers).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# --- 1. pixel class balance -------------------------------------------------
classes = ["background", "negative", "weak (1+)", "moderate (2+)", "strong (3+)"]
shares = [33.5, 47.3, 7.0, 3.6, 8.6]
colors = ["#e8e8e8", "#cfd8dc", "#ffd699", "#e08214", "#8c3d04"]

fig, ax = plt.subplots(figsize=(5.4, 3.4))
bars = ax.barh(classes[::-1], shares[::-1], color=colors[::-1], edgecolor="#333333", linewidth=0.7)
for bar, s in zip(bars, shares[::-1]):
    ax.text(bar.get_width() + 0.8, bar.get_y() + bar.get_height() / 2, f"{s:.1f}%",
            va="center", fontsize=8.5)
ax.set_xlabel("share of pixels, 792 fit tiles")
ax.set_xlim(0, 55)
ax.set_title("Training-target pixel balance", fontsize=10.5)
ax.grid(axis="x", alpha=0.3)
fig.tight_layout()
fig.savefig("pixel_class_balance.png", dpi=170)
print("wrote pixel_class_balance.png")

# --- 2. compute vs. accuracy tradeoff ---------------------------------------
fig, ax = plt.subplots(figsize=(4.6, 3.8))
points = [
    ("SegFormer-B0", 1.45, 0.443, "#8c8c8c"),
    ("ResNet18-UNet\n(ours)", 4.4, 0.746, "#2f6f5e"),
]
for label, t, miou, c in points:
    ax.scatter([t], [miou], s=140, color=c, zorder=3, edgecolor="#222222", linewidth=0.8)
    ax.annotate(label, (t, miou), textcoords="offset points", xytext=(10, -4), fontsize=9)

ax.annotate(
    "", xy=(4.4, 0.746), xytext=(1.45, 0.443),
    arrowprops=dict(arrowstyle="->", color="#a4423a", lw=1.3, linestyle=(0, (4, 2))),
)
ax.text(2.6, 0.58, "+0.303 tissue mIoU\nfor ~3x compute", fontsize=7.8, color="#a4423a",
        ha="center", style="italic")

ax.set_xlabel("CPU inference cost per image (s, fwd+bwd, batch 1)")
ax.set_ylabel("tissue mean IoU (validation)")
ax.set_xlim(0, 5.6)
ax.set_ylim(0.35, 0.85)
ax.set_title("Accuracy vs. compute, CPU-only", fontsize=10.5)
ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("efficiency_accuracy.png", dpi=170)
print("wrote efficiency_accuracy.png")
