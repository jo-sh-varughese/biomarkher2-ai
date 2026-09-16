"""Build a synthetic mock slide from real patches, and optionally exercise
Analyzer.predict() on it to prove tiling/stitching still works at
larger-than-patch scale.

This is Task 1 of tasks/person3_app_product.md: `Analyzer.predict()`
(app/analysis.py) already tiles an image of any size into the model's native
tile size and stitches predictions back -- built so Phase 3/6 (real
whole-slide images, whenever they arrive) wouldn't need new stitching logic,
just a bigger input. That has never been exercised at a scale bigger than one
1024x1024 patch. This script proves it works, and times how slow it is.

    python scripts/build_mock_slide.py
    python scripts/build_mock_slide.py --analyze artifacts/phase2_unet

See PHASE6_NOTES.md for the real numbers from the last run.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def find_patches(dataset_root: Path, required: int) -> list[tuple[str, Path]]:
    """Real image patches, interleaved across class folders.

    Round-robins across class_0/class_1+/class_2+/class_3+ (one file from
    each class per round) rather than taking the first N files in sorted
    order -- sorted order alone puts every tile in class_0, since that folder
    alone has more than `required` files and sorts first. A mock slide that
    only ever contains one class doesn't exercise the model or the classical
    baseline at a boundary between different staining intensities, which is
    the point of building it at all.
    """
    class_dirs = [d for d in sorted(dataset_root.iterdir()) if d.is_dir()]
    if not class_dirs:
        raise RuntimeError(f"No class folders found under {dataset_root}")

    per_class = [
        (d.name, [p for p in sorted(d.iterdir()) if p.suffix.lower() in IMAGE_EXTENSIONS])
        for d in class_dirs
    ]

    patches: list[tuple[str, Path]] = []
    index = 0
    while len(patches) < required:
        progressed = False
        for class_name, files in per_class:
            if index < len(files):
                patches.append((class_name, files[index]))
                progressed = True
                if len(patches) >= required:
                    break
        if not progressed:
            break
        index += 1
    return patches


def build_mock_slide(dataset_root: Path, output_path: Path, grid_size: int) -> tuple[Path, Path]:
    required = grid_size * grid_size
    patches = find_patches(dataset_root, required)

    if len(patches) < required:
        raise RuntimeError(
            f"Need at least {required} image patches under {dataset_root}, "
            f"but found only {len(patches)}."
        )

    with Image.open(patches[0][1]) as first_image:
        patch_width, patch_height = first_image.size

    for _, image_path in patches:
        with Image.open(image_path) as image:
            if image.size != (patch_width, patch_height):
                raise RuntimeError(
                    f"Patch size mismatch: {image_path} is {image.size}, "
                    f"expected {(patch_width, patch_height)}."
                )

    slide_width = patch_width * grid_size
    slide_height = patch_height * grid_size
    mock_slide = Image.new("RGB", (slide_width, slide_height))

    manifest_rows = []
    for index, (class_name, image_path) in enumerate(patches):
        row, col = divmod(index, grid_size)
        x, y = col * patch_width, row * patch_height
        with Image.open(image_path) as image:
            mock_slide.paste(image.convert("RGB"), (x, y))
        manifest_rows.append(
            {
                "grid_row": row,
                "grid_col": col,
                "x": x,
                "y": y,
                "width": patch_width,
                "height": patch_height,
                "class_folder": class_name,
                "source_patch": str(image_path),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    mock_slide.save(output_path)

    manifest_path = output_path.with_suffix(".csv")
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)

    print("Mock slide created successfully.")
    print(f"Grid: {grid_size} x {grid_size}")
    print(f"Patch size: {patch_width} x {patch_height}")
    print(f"Mock slide size: {slide_width} x {slide_height}")
    print(f"Classes used: {sorted({c for c, _ in patches})}")
    print(f"Image: {output_path}")
    print(f"Manifest: {manifest_path}")
    return output_path, manifest_path


def analyze_mock_slide(image_path: Path, manifest_path: Path, run_dir: Path) -> dict:
    """Run Analyzer.predict() over the whole mock slide, time it, and check
    that per-tile coordinate bookkeeping is correct: the tile at manifest row
    0 must predict identically whether it's read out of the stitched slide's
    prediction map or analyzed completely on its own. A coordinate bug (a
    transposed row/col, an off-by-one in the tiling loop) would make these
    two disagree even though the overall shape still looks fine.
    """
    from app.analysis import Analyzer

    analyzer = Analyzer(run_dir, run_dir / "resolved_config.yaml", "configs/preprocessing.yaml")

    slide = np.array(Image.open(image_path).convert("RGB"))

    start = time.perf_counter()
    prediction = analyzer.predict(slide)
    elapsed = time.perf_counter() - start

    if prediction.shape != slide.shape[:2]:
        raise RuntimeError(
            f"Stitched prediction shape {prediction.shape} does not cover the "
            f"whole slide {slide.shape[:2]} -- gap in the tiling logic."
        )

    with manifest_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    check_row = rows[0]
    x, y = int(check_row["x"]), int(check_row["y"])
    width, height = int(check_row["width"]), int(check_row["height"])
    tile_from_slide = prediction[y : y + height, x : x + width]

    standalone_rgb = np.array(Image.open(check_row["source_patch"]).convert("RGB"))
    standalone_prediction = analyzer.predict(standalone_rgb)

    coordinates_match = bool(np.array_equal(tile_from_slide, standalone_prediction))

    result = {
        "slide_width": int(slide.shape[1]),
        "slide_height": int(slide.shape[0]),
        "model_tile_size": analyzer.tile_size,
        "wall_clock_seconds": round(elapsed, 3),
        "checked_tile": check_row["source_patch"],
        "checked_tile_matches_standalone_prediction": coordinates_match,
    }

    print(f"Analyzer.predict() on the mock slide took {elapsed:.2f}s "
          f"({slide.shape[1]}x{slide.shape[0]} px, {analyzer.tile_size}px model tiles).")
    print("Coordinate check (tile read out of stitched slide vs. same tile "
          f"analyzed alone): {'MATCH' if coordinates_match else 'MISMATCH'}")
    if not coordinates_match:
        raise RuntimeError(
            "Per-tile coordinate bookkeeping is wrong: the same source patch "
            "predicts differently depending on whether it's read from the "
            "stitched slide or standalone."
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a synthetic mock slide from real HER2 patches, "
        "and optionally exercise Analyzer.predict() on it."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/raw/train"),
        help="Directory of class_0/class_1+/class_2+/class_3+ patch folders.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/mock_slide_4x4.png"),
        help="Output mock-slide image path.",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=4,
        help="Grid size. Default: 4 for a 4x4 slide.",
    )
    parser.add_argument(
        "--analyze",
        type=Path,
        default=None,
        metavar="RUN_DIR",
        help="Run Analyzer.predict() on the built slide using this training "
        "run directory (must contain best.pt and resolved_config.yaml), "
        "record wall-clock time, and check per-tile coordinate correctness.",
    )
    parser.add_argument(
        "--analysis-output",
        type=Path,
        default=Path("artifacts/mock_slide_4x4_analysis.json"),
        help="Where to write the --analyze results as JSON.",
    )
    args = parser.parse_args()

    if args.grid < 1:
        raise ValueError("Grid size must be at least 1.")

    image_path, manifest_path = build_mock_slide(
        dataset_root=args.dataset,
        output_path=args.output,
        grid_size=args.grid,
    )

    if args.analyze is not None:
        result = analyze_mock_slide(image_path, manifest_path, args.analyze)
        args.analysis_output.parent.mkdir(parents=True, exist_ok=True)
        args.analysis_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Analysis result: {args.analysis_output}")


if __name__ == "__main__":
    main()
