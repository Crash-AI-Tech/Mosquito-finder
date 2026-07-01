#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from evaluate_candidate_search_heuristics import (
    candidate_hits_gt,
    find_candidates,
    xywh_to_xyxy,
)


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
    "candidate_score",
    "candidate_source",
]


@dataclass
class CropRecord:
    output_path: Path
    split: str
    label: str
    binary_label: int
    index: int
    variant: str
    scenario: str
    hard_negative_type: str
    candidate_score: float
    candidate_source: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a candidate-crop eval manifest from Stage-1 heuristic proposals."
    )
    parser.add_argument("--ann-file", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--split-name", default="reality2017")
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--step", type=int, default=18)
    parser.add_argument("--margin", type=int, default=36)
    parser.add_argument("--local-contrast-threshold", type=float, default=0.06)
    parser.add_argument("--background-variance-threshold", type=float, default=0.018)
    parser.add_argument("--hit-center-multiplier", type=float, default=1.8)
    parser.add_argument("--hit-min-padding", type=float, default=16.0)
    parser.add_argument("--include-negative-images", action="store_true")
    return parser


def expanded_crop(box: np.ndarray, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(value) for value in box]
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    side = max(width, height, 48.0) * 1.85
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    left = max(0, int(round(cx - side / 2.0)))
    top = max(0, int(round(cy - side / 2.0)))
    right = min(image_width, int(round(cx + side / 2.0)))
    bottom = min(image_height, int(round(cy + side / 2.0)))
    return left, top, max(left + 1, right), max(top + 1, bottom)


def save_crop(image: Image.Image, crop: tuple[int, int, int, int], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.crop(crop).resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR).save(output_path, quality=94)


def row(record: CropRecord) -> dict[str, Any]:
    return {
        "file_name": record.output_path.name,
        "relative_path": record.output_path.relative_to(REPO_ROOT).as_posix(),
        "date": "20260702",
        "source": "stage1_heuristic_candidate",
        "scene": record.split,
        "zoom": "search_candidate_crop",
        "torch": "auto",
        "label": record.label,
        "binary_label": record.binary_label,
        "index": f"{record.index:06d}",
        "base_id": f"20260702_stage1_candidate_{record.split}_{record.index:06d}",
        "variant": record.variant,
        "variant_tag": "stage1_candidate_eval_crop",
        "image_width": IMAGE_SIZE,
        "image_height": IMAGE_SIZE,
        "fold": {"train2017": 0, "val2017": 1, "reality2017": 2}.get(record.split, 9),
        "split": record.split,
        "scenario": record.scenario,
        "hard_negative_type": record.hard_negative_type,
        "candidate_score": f"{record.candidate_score:.6f}",
        "candidate_source": record.candidate_source,
    }


def main() -> int:
    args = build_parser().parse_args()
    args.image_dir = args.image_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.manifest = args.manifest.resolve()
    payload = json.loads(args.ann_file.read_text(encoding="utf-8"))
    annotations_by_image: dict[int, list[np.ndarray]] = {int(image["id"]): [] for image in payload["images"]}
    for annotation in payload["annotations"]:
        annotations_by_image.setdefault(int(annotation["image_id"]), []).append(xywh_to_xyxy(annotation["bbox"]))

    records: list[CropRecord] = []
    counts = {"candidate_positive": 0, "candidate_negative": 0, "images_with_candidates": 0}
    for image_meta in payload["images"]:
        image_id = int(image_meta["id"])
        image_path = args.image_dir / str(image_meta["file_name"])
        image_bgr = cv2.imread(str(image_path))
        if image_bgr is None:
            raise FileNotFoundError(image_path)
        gt_boxes = np.array(annotations_by_image.get(image_id, []), dtype=np.float32).reshape((-1, 4))
        if len(gt_boxes) == 0 and not args.include_negative_images:
            continue

        candidates = find_candidates(
            image_bgr,
            step=args.step,
            margin=args.margin,
            local_contrast_threshold=args.local_contrast_threshold,
            background_variance_threshold=args.background_variance_threshold,
            max_candidates=args.max_candidates,
        )[: args.max_candidates]
        if candidates:
            counts["images_with_candidates"] += 1

        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            for candidate_index, candidate in enumerate(candidates):
                is_positive = candidate_hits_gt(
                    candidate,
                    gt_boxes,
                    center_multiplier=args.hit_center_multiplier,
                    min_padding=args.hit_min_padding,
                )
                label = "candidate_positive" if is_positive else "candidate_negative"
                counts[label] += 1
                output_path = (
                    args.output_dir
                    / label
                    / f"{args.split_name}_{image_id:06d}_{candidate_index:02d}_{candidate.source}.jpg"
                )
                save_crop(image, expanded_crop(candidate.box, image.width, image.height), output_path)
                records.append(
                    CropRecord(
                        output_path=output_path,
                        split=args.split_name,
                        label=label,
                        binary_label=1 if is_positive else 0,
                        index=len(records) + 1,
                        variant=f"{candidate_index:02d}",
                        scenario=str(image_meta.get("scenario", "unknown")),
                        hard_negative_type=str(image_meta.get("hard_negative_type", "none")),
                        candidate_score=candidate.score,
                        candidate_source=candidate.source,
                    )
                )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(row(record) for record in records)

    summary = {
        "ann_file": str(args.ann_file),
        "image_dir": str(args.image_dir),
        "output_dir": str(args.output_dir),
        "manifest": str(args.manifest),
        "counts": counts,
        "total": len(records),
    }
    (args.manifest.parent / "candidate_eval_from_heuristics_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
