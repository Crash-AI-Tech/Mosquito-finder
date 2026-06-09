#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = REPO_ROOT / "data" / "processed" / "combined_mosquito_coco_single_class"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "classifier" / "real_detector_crops"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "artifacts" / "classifier_real_detector_crops" / "manifest.csv"
IMAGE_SIZE = 64
MANIFEST_FIELDS = [
    "file_name",
    "relative_path",
    "date",
    "source",
    "scene",
    "zoom",
    "torch",
    "label",
    "binary_label",
    "index",
    "base_id",
    "variant",
    "variant_tag",
    "image_width",
    "image_height",
    "fold",
    "split",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create Stage-2 classifier crops from detector COCO data."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--negative-per-image", type=int, default=3)
    parser.add_argument("--padding-ratio", type=float, default=2.2)
    parser.add_argument("--seed", type=int, default=20260531)
    parser.add_argument(
        "--splits",
        nargs="+",
        default=None,
        help="COCO split directories to process. Defaults to every instances_*.json under annotations/.",
    )
    parser.add_argument("--clean", action="store_true")
    return parser


def load_coco(dataset_dir: Path, split: str) -> tuple[list[dict[str, Any]], dict[int, list[list[float]]]]:
    annotation_path = dataset_dir / "annotations" / f"instances_{split}.json"
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    boxes_by_image: dict[int, list[list[float]]] = {int(image["id"]): [] for image in payload["images"]}
    for annotation in payload["annotations"]:
        boxes_by_image.setdefault(int(annotation["image_id"]), []).append(annotation["bbox"])
    return payload["images"], boxes_by_image


def discover_splits(dataset_dir: Path, requested_splits: list[str] | None) -> list[str]:
    if requested_splits:
        return requested_splits
    annotation_dir = dataset_dir / "annotations"
    splits = []
    for annotation_path in sorted(annotation_dir.glob("instances_*.json")):
        splits.append(annotation_path.stem.removeprefix("instances_"))
    if not splits:
        raise FileNotFoundError(f"No COCO annotations found under {annotation_dir}")
    return splits


def expanded_box(
    box: list[float],
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> tuple[int, int, int, int]:
    x, y, width, height = box
    cx = x + width / 2
    cy = y + height / 2
    side = max(width, height, 16) * padding_ratio
    left = max(0, int(round(cx - side / 2)))
    top = max(0, int(round(cy - side / 2)))
    right = min(image_width, int(round(cx + side / 2)))
    bottom = min(image_height, int(round(cy + side / 2)))
    return left, top, max(left + 1, right), max(top + 1, bottom)


def intersects(candidate: tuple[int, int, int, int], boxes: list[list[float]]) -> bool:
    left, top, right, bottom = candidate
    for x, y, width, height in boxes:
        box_left = int(x)
        box_top = int(y)
        box_right = int(x + width)
        box_bottom = int(y + height)
        if left < box_right and right > box_left and top < box_bottom and bottom > box_top:
            return True
    return False


def random_negative_box(
    rng: random.Random,
    image_width: int,
    image_height: int,
    positive_boxes: list[list[float]],
) -> tuple[int, int, int, int]:
    for _ in range(80):
        side = rng.randint(40, 112)
        left = rng.randint(0, max(0, image_width - side))
        top = rng.randint(0, max(0, image_height - side))
        candidate = (left, top, min(image_width, left + side), min(image_height, top + side))
        if not intersects(candidate, positive_boxes):
            return candidate
    side = min(image_width, image_height, 96)
    return 0, 0, side, side


def split_to_fold(split: str) -> int:
    known = {"train2017": 0, "val2017": 1, "reality2017": 2}
    if split in known:
        return known[split]
    return int(hashlib.sha1(split.encode("utf-8")).hexdigest()[:6], 16) % 1000 + 10


def save_crop(
    image: Image.Image,
    crop_box: tuple[int, int, int, int],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop(crop_box).resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR).save(
        output_path,
        quality=94,
    )


def manifest_row(
    file_name: str,
    relative_path: Path,
    split: str,
    label: str,
    binary_label: int,
    index: int,
    variant: str,
) -> dict[str, Any]:
    base_id = f"20260531_detector_{split}_roi_auto_{label}_{index:05d}"
    return {
        "file_name": file_name,
        "relative_path": relative_path.as_posix(),
        "date": "20260531",
        "source": "detector",
        "scene": split,
        "zoom": "roi",
        "torch": "auto",
        "label": label,
        "binary_label": binary_label,
        "index": f"{index:05d}",
        "base_id": base_id,
        "variant": variant,
        "variant_tag": "detector_crop",
        "image_width": IMAGE_SIZE,
        "image_height": IMAGE_SIZE,
        "fold": split_to_fold(split),
        "split": split,
    }


def main() -> None:
    args = build_parser().parse_args()
    args.dataset_dir = args.dataset_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.manifest = args.manifest.resolve()
    rng = random.Random(args.seed)
    splits = discover_splits(args.dataset_dir, args.splits)

    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    rows: list[dict[str, Any]] = []
    counts = {"mosquito": 0, "hardnegative": 0}

    for split in splits:
        images, boxes_by_image = load_coco(args.dataset_dir, split)
        for image_info in images:
            image_id = int(image_info["id"])
            image_path = args.dataset_dir / split / image_info["file_name"]
            positive_boxes = boxes_by_image.get(image_id, [])
            with Image.open(image_path) as image:
                rgb = image.convert("RGB")
                for box_index, box in enumerate(positive_boxes):
                    counts["mosquito"] += 1
                    file_name = f"{split}_{image_id:05d}_pos_{box_index:02d}.jpg"
                    output_path = args.output_dir / "mosquito" / file_name
                    save_crop(
                        rgb,
                        expanded_box(box, rgb.width, rgb.height, args.padding_ratio),
                        output_path,
                    )
                    rows.append(
                        manifest_row(
                            file_name,
                            output_path.relative_to(REPO_ROOT),
                            split,
                            "mosquito",
                            1,
                            counts["mosquito"],
                            f"pos{box_index:02d}",
                        )
                    )

                negative_count = args.negative_per_image
                if not positive_boxes:
                    negative_count += 2
                for negative_index in range(negative_count):
                    counts["hardnegative"] += 1
                    file_name = f"{split}_{image_id:05d}_neg_{negative_index:02d}.jpg"
                    output_path = args.output_dir / "hardnegative" / file_name
                    save_crop(
                        rgb,
                        random_negative_box(rng, rgb.width, rgb.height, positive_boxes),
                        output_path,
                    )
                    rows.append(
                        manifest_row(
                            file_name,
                            output_path.relative_to(REPO_ROOT),
                            split,
                            "hardnegative",
                            0,
                            counts["hardnegative"],
                            f"neg{negative_index:02d}",
                        )
                    )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "manifest": args.manifest.relative_to(REPO_ROOT).as_posix(),
        "output_dir": args.output_dir.relative_to(REPO_ROOT).as_posix(),
        "dataset_dir": args.dataset_dir.relative_to(REPO_ROOT).as_posix()
        if args.dataset_dir.is_relative_to(REPO_ROOT)
        else str(args.dataset_dir),
        "splits": splits,
        "image_size": IMAGE_SIZE,
        "counts": counts,
        "total": len(rows),
    }
    summary_path = args.manifest.parent / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
