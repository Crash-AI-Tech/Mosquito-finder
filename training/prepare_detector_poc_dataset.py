#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "detector"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "detector_poc"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = ["mosquito"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a YOLO-format detector POC dataset from reviewed mosquito images."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260530)
    parser.add_argument("--clean", action="store_true")
    return parser


def load_annotation(label_path: Path) -> dict[str, Any]:
    if not label_path.exists():
        return {"boxes": []}
    with label_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload.get("boxes", []), list):
        raise ValueError(f"Invalid boxes in {label_path}")
    return payload


def to_yolo_box(box: dict[str, Any], image_width: int, image_height: int) -> str:
    label = str(box.get("label", "mosquito"))
    if label not in CLASS_NAMES:
        raise ValueError(f"Unsupported detector label: {label}")

    x = float(box["x"])
    y = float(box["y"])
    width = float(box["width"])
    height = float(box["height"])

    center_x = (x + width / 2) / image_width
    center_y = (y + height / 2) / image_height
    norm_width = width / image_width
    norm_height = height / image_height
    class_id = CLASS_NAMES.index(label)

    values = [center_x, center_y, norm_width, norm_height]
    if any(value < 0 or value > 1 for value in values):
        raise ValueError(f"Box is outside image bounds: {box}")

    return f"{class_id} {center_x:.6f} {center_y:.6f} {norm_width:.6f} {norm_height:.6f}"


def scan_images(source_dir: Path) -> list[Path]:
    image_dir = source_dir / "images"
    if not image_dir.exists():
        raise FileNotFoundError(f"Missing detector image directory: {image_dir}")
    images = [
        path for path in sorted(image_dir.iterdir())
        if path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not images:
        raise FileNotFoundError(f"No detector images found in {image_dir}")
    return images


def split_images(images: list[Path], val_ratio: float, seed: int) -> dict[str, list[Path]]:
    shuffled = list(images)
    random.Random(seed).shuffle(shuffled)
    val_count = max(1, int(round(len(shuffled) * val_ratio))) if len(shuffled) > 1 else 0
    return {
        "val": sorted(shuffled[:val_count]),
        "train": sorted(shuffled[val_count:]),
    }


def write_dataset_yaml(output_dir: Path) -> None:
    yaml_text = "\n".join(
        [
            f"path: {output_dir.as_posix()}",
            "train: images/train",
            "val: images/val",
            "names:",
            *[f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES)],
            "",
        ]
    )
    (output_dir / "dataset.yaml").write_text(yaml_text, encoding="utf-8")


def prepare_dataset(source_dir: Path, output_dir: Path, val_ratio: float, seed: int, clean: bool) -> None:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    splits = split_images(scan_images(source_dir), val_ratio=val_ratio, seed=seed)
    summary: dict[str, Any] = {"class_names": CLASS_NAMES, "splits": {}}

    for split, images in splits.items():
        image_output_dir = output_dir / "images" / split
        label_output_dir = output_dir / "labels" / split
        image_output_dir.mkdir(parents=True, exist_ok=True)
        label_output_dir.mkdir(parents=True, exist_ok=True)

        positive_count = 0
        box_count = 0
        for image_path in images:
            annotation = load_annotation(source_dir / "labels" / f"{image_path.stem}.json")
            with Image.open(image_path) as image:
                image_width, image_height = image.size

            yolo_rows = [
                to_yolo_box(box, image_width=image_width, image_height=image_height)
                for box in annotation.get("boxes", [])
            ]
            if yolo_rows:
                positive_count += 1
                box_count += len(yolo_rows)

            shutil.copy2(image_path, image_output_dir / image_path.name)
            (label_output_dir / f"{image_path.stem}.txt").write_text(
                "\n".join(yolo_rows) + ("\n" if yolo_rows else ""),
                encoding="utf-8",
            )

        summary["splits"][split] = {
            "images": len(images),
            "positive_images": positive_count,
            "negative_images": len(images) - positive_count,
            "boxes": box_count,
        }

    write_dataset_yaml(output_dir)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = build_parser().parse_args()
    prepare_dataset(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        val_ratio=args.val_ratio,
        seed=args.seed,
        clean=args.clean,
    )
    print(f"Detector POC dataset written to {args.output_dir}")


if __name__ == "__main__":
    main()
