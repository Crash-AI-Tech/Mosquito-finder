#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_SIZE = 96
FIELDS = [
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
    "scenario",
    "hard_negative_type",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build candidate-search crop data from COCO detector datasets.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--negative-per-image", type=int, default=4)
    parser.add_argument("--padding-ratio", type=float, default=3.2)
    parser.add_argument("--seed", type=int, default=20260701)
    parser.add_argument("--clean", action="store_true")
    return parser


def load_coco(dataset_dir: Path, split: str) -> tuple[list[dict[str, Any]], dict[int, list[list[float]]]]:
    payload = json.loads((dataset_dir / "annotations" / f"instances_{split}.json").read_text(encoding="utf-8"))
    boxes_by_image: dict[int, list[list[float]]] = {int(image["id"]): [] for image in payload["images"]}
    for annotation in payload["annotations"]:
        boxes_by_image.setdefault(int(annotation["image_id"]), []).append(annotation["bbox"])
    return payload["images"], boxes_by_image


def discover_splits(dataset_dir: Path) -> list[str]:
    splits = []
    for path in sorted((dataset_dir / "annotations").glob("instances_*.json")):
        splits.append(path.stem.removeprefix("instances_"))
    if not splits:
        raise FileNotFoundError(f"No instances_*.json files under {dataset_dir / 'annotations'}")
    return splits


def expanded_box(box: list[float], width: int, height: int, ratio: float) -> tuple[int, int, int, int]:
    x, y, w, h = box
    cx = x + w / 2
    cy = y + h / 2
    side = max(w, h, 14) * ratio
    left = max(0, int(round(cx - side / 2)))
    top = max(0, int(round(cy - side / 2)))
    right = min(width, int(round(cx + side / 2)))
    bottom = min(height, int(round(cy + side / 2)))
    return left, top, max(left + 1, right), max(top + 1, bottom)


def intersects(candidate: tuple[int, int, int, int], boxes: list[list[float]]) -> bool:
    left, top, right, bottom = candidate
    for x, y, width, height in boxes:
        if left < x + width and right > x and top < y + height and bottom > y:
            return True
    return False


def negative_box(rng: random.Random, width: int, height: int, boxes: list[list[float]]) -> tuple[int, int, int, int]:
    for _ in range(100):
        side = rng.randint(42, min(max(48, min(width, height)), 132))
        left = rng.randint(0, max(0, width - side))
        top = rng.randint(0, max(0, height - side))
        candidate = (left, top, min(width, left + side), min(height, top + side))
        if not intersects(candidate, boxes):
            return candidate
    side = min(width, height, 96)
    return 0, 0, side, side


def save_crop(image: Image.Image, crop: tuple[int, int, int, int], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop(crop).resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR).save(output_path, quality=94)


def row(
    output_path: Path,
    split: str,
    label: str,
    binary_label: int,
    index: int,
    variant: str,
    scenario: str,
    hard_negative_type: str,
) -> dict[str, Any]:
    file_name = output_path.name
    return {
        "file_name": file_name,
        "relative_path": output_path.relative_to(REPO_ROOT).as_posix(),
        "date": "20260701",
        "source": "candidate_search",
        "scene": split,
        "zoom": "search_crop",
        "torch": "auto",
        "label": label,
        "binary_label": binary_label,
        "index": f"{index:06d}",
        "base_id": f"20260701_candidate_{split}_{label}_{index:06d}",
        "variant": variant,
        "variant_tag": "candidate_search_crop",
        "image_width": IMAGE_SIZE,
        "image_height": IMAGE_SIZE,
        "fold": {"train2017": 0, "val2017": 1, "reality2017": 2}.get(split, 9),
        "split": split,
        "scenario": scenario,
        "hard_negative_type": hard_negative_type,
    }


def main() -> None:
    args = build_parser().parse_args()
    args.dataset_dir = args.dataset_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.manifest = args.manifest.resolve()
    rng = random.Random(args.seed)

    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    rows: list[dict[str, Any]] = []
    counts = {"candidate": 0, "background_trap": 0}
    for split in discover_splits(args.dataset_dir):
        images, boxes_by_image = load_coco(args.dataset_dir, split)
        for image_info in images:
            image_id = int(image_info["id"])
            image_path = args.dataset_dir / split / image_info["file_name"]
            boxes = boxes_by_image.get(image_id, [])
            scenario = str(image_info.get("scenario", "unknown"))
            hard_negative_type = str(image_info.get("hard_negative_type", "unknown"))

            with Image.open(image_path) as opened:
                image = opened.convert("RGB")
                for box_index, box in enumerate(boxes):
                    counts["candidate"] += 1
                    output_path = args.output_dir / "candidate" / f"{split}_{image_id:06d}_pos_{box_index:02d}.jpg"
                    save_crop(image, expanded_box(box, image.width, image.height, args.padding_ratio), output_path)
                    rows.append(row(output_path, split, "candidate", 1, counts["candidate"], f"pos{box_index:02d}", scenario, hard_negative_type))

                negative_count = args.negative_per_image + (2 if not boxes else 0)
                for negative_index in range(negative_count):
                    counts["background_trap"] += 1
                    output_path = args.output_dir / "background_trap" / f"{split}_{image_id:06d}_neg_{negative_index:02d}.jpg"
                    save_crop(image, negative_box(rng, image.width, image.height, boxes), output_path)
                    rows.append(row(output_path, split, "background_trap", 0, counts["background_trap"], f"neg{negative_index:02d}", scenario, hard_negative_type))

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "dataset_dir": str(args.dataset_dir),
        "output_dir": str(args.output_dir),
        "manifest": str(args.manifest),
        "image_size": IMAGE_SIZE,
        "counts": counts,
        "total": len(rows),
    }
    (args.manifest.parent / "candidate_search_crops_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
