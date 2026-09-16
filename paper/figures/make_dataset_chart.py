"""Dataset class-distribution chart for the paper: HER2_IHC_40X test-split
patch counts per folder label (HER2 intensity class), the numbers this
repo's own dataset audit established (PHASE2.md / the public-patch-dataset
memory) -- not invented for this figure.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

classes = ["0", "1+", "2+", "3+"]
counts = [758, 538, 226, 678]
colors = ["#f0f0f0", "#cfd8dc", "#e08214", "#8c3d04"]
total = sum(counts)

fig, ax = plt.subplots(figsize=(4.6, 3.6))
bars = ax.bar(classes, counts, color=colors, edgecolor="#333333", linewidth=0.8)
for bar, c in zip(bars, counts):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 12,
            f"{c}\n({c/total*100:.0f}%)", ha="center", fontsize=8.5)

ax.set_xlabel("HER2 intensity class (folder label)")
ax.set_ylabel("patches")
ax.set_title(f"HER2_IHC_40X test split (n={total})", fontsize=10.5)
ax.set_ylim(0, 900)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig("dataset_distribution.png", dpi=170)
print("wrote dataset_distribution.png")
