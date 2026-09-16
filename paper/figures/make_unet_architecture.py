"""U-Net architecture schematic for the paper -- drawn from the actual
forward() pass in models/unet_seg.py (ResNetUNet), not a generic textbook
diagram: real channel counts and strides for this project's model.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(7.2, 4.6))
ax.set_xlim(0, 12.5)
ax.set_ylim(0, 8)
ax.axis("off")

def box(x, y, w, h, text, color="#dce6e8", fontsize=7.6, edge="#2f3e46"):
    b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.07",
                        linewidth=1.1, edgecolor=edge, facecolor=color)
    ax.add_patch(b)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize)

def arrow(p0, p1, color="#2f3e46", style="-|>", lw=1.2, ls="solid"):
    a = FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=11,
                         linewidth=lw, color=color, shrinkA=1, shrinkB=1, linestyle=ls)
    ax.add_patch(a)

encoder_color = "#cfe0e8"
decoder_color = "#e8dcc8"
bottleneck_color = "#d8c8e0"

# Encoder (left column, top to bottom)
box(0.1, 6.9, 2.3, 0.8, "Input\nRGB + DAB OD\n4 x 512 x 512", color="#f2f2f2")
box(0.1, 5.85, 2.3, 0.75, "conv1 (7x7,s2)\n$s_0$: 64ch, stride 2", color=encoder_color)
box(0.1, 4.8, 2.3, 0.75, "maxpool+layer1\n$s_1$: 64ch, stride 4", color=encoder_color)
box(0.1, 3.75, 2.3, 0.75, "layer2\n$s_2$: 128ch, stride 8", color=encoder_color)
box(0.1, 2.7, 2.3, 0.75, "layer3\n$s_3$: 256ch, stride 16", color=encoder_color)
box(0.1, 1.65, 2.3, 0.75, "layer4 (bottleneck)\n$s_4$: 512ch, stride 32", color=bottleneck_color)

for y0, y1 in [(6.9, 6.6), (5.85, 5.55), (4.8, 4.5), (3.75, 3.45), (2.7, 2.4)]:
    arrow((1.25, y0), (1.25, y1))

# Decoder (right column, bottom to top), mirrors encoder depth
box(9.9, 1.65, 2.5, 0.75, "up4: bilinear x2\n+ skip $s_3$ -> 256ch, s16", color=decoder_color)
box(9.9, 2.7, 2.5, 0.75, "up3: bilinear x2\n+ skip $s_2$ -> 128ch, s8", color=decoder_color)
box(9.9, 3.75, 2.5, 0.75, "up2: bilinear x2\n+ skip $s_1$ -> 64ch, s4", color=decoder_color)
box(9.9, 4.8, 2.5, 0.75, "up1: bilinear x2\n+ skip $s_0$ -> 64ch, s2", color=decoder_color)
box(9.9, 5.85, 2.5, 0.75, "1x1 conv classifier\n5 classes, stride 2", color="#f0e2c8")
box(9.9, 6.9, 2.5, 0.8, "bilinear upsample\nlogits: 5 x 512 x 512", color="#f2f2f2")

for y0, y1 in [(2.4, 2.7), (3.45, 3.75), (4.5, 4.8), (5.55, 5.85), (6.6, 6.9)]:
    arrow((11.15, y0), (11.15, y1))

# Bottleneck bridge
arrow((2.4, 2.025), (9.9, 2.025))
ax.text(6.15, 2.22, "bottleneck", ha="center", fontsize=7, style="italic", color="#555555")

# Skip connections (dashed, horizontal, encoder -> decoder at matching stride)
skip_pairs = [
    (6.6, "$s_0$"), (5.55, "$s_1$"), (4.5, "$s_2$"), (3.45, "$s_3$"),
]
for y, label in skip_pairs:
    arrow((2.4, y), (9.9, y), color="#a4423a", lw=1.1, ls=(0, (4, 2)))
    ax.text(6.15, y + 0.18, f"skip {label}", ha="center", fontsize=6.8, color="#a4423a")

ax.text(0.1, 0.55,
        "Solid arrows: encoder / decoder data flow.  Dashed arrows: skip connections\n"
        "(encoder features concatenated into the matching decoder stage).\n"
        "The 4th input channel (DAB optical density) is the paper's input-fusion contribution.",
        fontsize=7, style="italic", color="#333333")

fig.tight_layout()
fig.savefig("unet_architecture.png", dpi=170)
print("wrote unet_architecture.png")
