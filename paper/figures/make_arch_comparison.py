"""One-off script to render the SegFormer-vs-UNet per-class IoU comparison
figure for the paper, from the numbers already reported in PHASE5.md. Not
part of the reproducible pipeline in scripts/ -- run once, output committed
as a static image like the other paper figures.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

classes = ["background", "negative", "weak (1+)", "moderate (2+)", "strong (3+)"]
segformer = [0.852, 0.815, 0.341, 0.00006, 0.618]
unet = [0.861, 0.839, 0.666, 0.589, 0.891]

x = np.arange(len(classes))
width = 0.38

fig, ax = plt.subplots(figsize=(7, 4.2))
b1 = ax.bar(x - width / 2, segformer, width, label="SegFormer-B0", color="#8c8c8c")
b2 = ax.bar(x + width / 2, unet, width, label="ResNet18-UNet (ours)", color="#2f6f5e")

for bars in (b1, b2):
    for bar in bars:
        h = bar.get_height()
        label = f"{h:.3f}" if h >= 0.001 else "~0"
        ax.text(bar.get_x() + bar.get_width() / 2, h + 0.015, label,
                ha="center", fontsize=7.5)

ax.set_xticks(x, classes, rotation=15, ha="right", fontsize=9)
ax.set_ylim(0, 1.0)
ax.set_ylabel("validation IoU")
ax.set_title("Per-class IoU: SegFormer-B0 vs. ResNet18-UNet\n(identical data, split, seed, 4 epochs, CPU-only)", fontsize=10)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=9)
fig.tight_layout()
fig.savefig("architecture_comparison.png", dpi=160)
print("wrote architecture_comparison.png")
