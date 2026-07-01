#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


MODEL_SIZE = 416


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a sliced/tiled COCO detector dataset from phone-frame COCO data for small-object training."
    )
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phone-frame-dir", type=Path)
    parser.add_argument("--splits", nargs="+", default=["train2017", "val2017", "reality2017"])
    parser.add_argument("--tile-size", type=int, default=640)
    parser.add_argument("--overlap", type=float, default=0.42)
    parser.add_argument("--model-size", type=int, default=MODEL_SIZE)
    parser.add_argument("--min-visible-ratio", type=float, default=0.35)
    parser.add_argument("--negative-keep-prob", type=float, default=0.22)
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--clean", action="store_true")
    return parser


def load_payload(dataset_dir: Path, split: str) -> dict[str, Any] | None:
    ann_path = dataset_dir / "annotations" / f"instances_{split}.json"
    if not ann_path.exists():
        return None
    return json.loads(ann_path.read_text(encoding="utf-8"))


def source_box(annotation: dict[str, Any], image_meta: dict[str, Any]) -> tuple[float, float, float, float]:
    if "source_phone_box" in annotation:
        return tuple(float(value) for value in annotation["source_phone_box"])

    source_width = float(image_meta.get("source_width", image_meta["width"]))
    source_height = float(image_meta.get("source_height", image_meta["height"]))
    x, y, width, height = [float(value) for value in annotation["bbox"]]
    return (
        x / float(image_meta["width"]) * source_width,
        y / float(image_meta["height"]) * source_height,
        width / float(image_meta["width"]) * source_width,
        height / float(image_meta["height"]) * source_height,
    )


def tile_origins(length: int, tile_size: int, overlap: float) -> list[int]:
    if length <= tile_size:
        return [0]
    stride = max(1, int(round(tile_size * (1.0 - overlap))))
    origins = list(range(0, max(1, length - tile_size + 1), stride))
    if origins[-1] != length - tile_size:
        origins.append(length - tile_size)
    return sorted(set(origins))


def intersect_box(
    box: tuple[float, float, float, float],
    tile: tuple[int, int, int, int],
) -> tuple[float, float, float, float] | None:
    x, y, width, height = box
    bx1, by1, bx2, by2 = x, y, x + width, y + height
    tx1, ty1, tx2, ty2 = [float(value) for value in tile]
    ix1 = max(bx1, tx1)
    iy1 = max(by1, ty1)
    ix2 = min(bx2, tx2)
    iy2 = min(by2, ty2)
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return ix1, iy1, ix2 - ix1, iy2 - iy1


def visible_ratio(original: tuple[float, float, float, float], clipped: tuple[float, float, float, float]) -> float:
    original_area = max(1e-6, original[2] * original[3])
    return max(0.0, clipped[2] * clipped[3]) / original_area


def transform_to_model_box(
    clipped: tuple[float, float, float, float],
    tile_left: int,
    tile_top: int,
    tile_size: int,
    model_size: int,
) -> list[float]:
    scale = model_size / float(tile_size)
    x, y, width, height = clipped
    return [
        round((x - tile_left) * scale, 3),
        round((y - tile_top) * scale, 3),
        round(width * scale, 3),
        round(height * scale, 3),
    ]


def image_path_for(dataset_dir: Path, phone_frame_dir: Path | None, split: str, image_meta: dict[str, Any]) -> Path:
    if phone_frame_dir is not None:
        phone_path = phone_frame_dir / split / str(image_meta["file_name"])
        if phone_path.exists():
            return phone_path
    return dataset_dir / split / str(image_meta["file_name"])


def build_split(
    dataset_dir: Path,
    phone_frame_dir: Path | None,
    output_dir: Path,
    split: str,
    tile_size: int,
    overlap: float,
    model_size: int,
    min_visible_ratio: float,
    negative_keep_prob: float,
    rng: random.Random,
) -> dict[str, Any]:
    payload = load_payload(dataset_dir, split)
    if payload is None:
        return {"split": split, "skipped": True, "reason": "missing annotation file"}

    annotations_by_image: dict[int, list[dict[str, Any]]] = {int(image["id"]): [] for image in payload["images"]}
    for annotation in payload["annotations"]:
        annotations_by_image.setdefault(int(annotation["image_id"]), []).append(annotation)

    out_image_dir = output_dir / split
    out_image_dir.mkdir(parents=True, exist_ok=True)
    out_images: list[dict[str, Any]] = []
    out_annotations: list[dict[str, Any]] = []
    image_id_next = 1
    annotation_id_next = 1
    positive_tiles = 0
    negative_tiles = 0

    for image_meta in payload["images"]:
        source_path = image_path_for(dataset_dir, phone_frame_dir, split, image_meta)
        with Image.open(source_path) as opened:
            image = opened.convert("RGB")

        boxes = [source_box(annotation, image_meta) for annotation in annotations_by_image.get(int(image_meta["id"]), [])]
        category_ids = [
            int(annotation.get("category_id", payload.get("categories", [{"id": 0}])[0]["id"]))
            for annotation in annotations_by_image.get(int(image_meta["id"]), [])
        ]

        tile_width = min(tile_size, image.width)
        tile_height = min(tile_size, image.height)
        for tile_top in tile_origins(image.height, tile_height, overlap):
            for tile_left in tile_origins(image.width, tile_width, overlap):
                tile = (tile_left, tile_top, tile_left + tile_width, tile_top + tile_height)
                tile_annotations: list[tuple[list[float], int, float]] = []

                for box, category_id in zip(boxes, category_ids):
                    clipped = intersect_box(box, tile)
                    if clipped is None or visible_ratio(box, clipped) < min_visible_ratio:
                        continue
                    model_box = transform_to_model_box(clipped, tile_left, tile_top, tile_width, model_size)
                    if model_box[2] >= 1.0 and model_box[3] >= 1.0:
                        tile_annotations.append((model_box, category_id, model_box[2] * model_box[3]))

                if not tile_annotations and rng.random() > negative_keep_prob:
                    continue

                suffix = f"{Path(str(image_meta['file_name'])).stem}_x{tile_left:04d}_y{tile_top:04d}.jpg"
                tile_name = f"{split}_{image_id_next:07d}_{suffix}"
                resized_tile = image.crop(tile).resize((model_size, model_size), Image.Resampling.BILINEAR)
                resized_tile.save(out_image_dir / tile_name, quality=92)

                out_images.append(
                    {
                        "id": image_id_next,
                        "file_name": tile_name,
                        "width": model_size,
                        "height": model_size,
                        "source_file_name": image_meta["file_name"],
                        "source_image_id": int(image_meta["id"]),
                        "source_width": image.width,
                        "source_height": image.height,
                        "tile_left": tile_left,
                        "tile_top": tile_top,
                        "tile_size": tile_width,
                        "tile_overlap": overlap,
                        "sliced": True,
                        "scenario": image_meta.get("scenario", "unknown"),
                    }
                )

                if tile_annotations:
                    positive_tiles += 1
                else:
                    negative_tiles += 1

                for bbox, category_id, area in tile_annotations:
                    out_annotations.append(
                        {
                            "id": annotation_id_next,
                            "image_id": image_id_next,
                            "category_id": category_id,
                            "bbox": bbox,
                            "area": round(area, 3),
                            "iscrowd": 0,
                            "sliced": True,
                        }
                    )
                    annotation_id_next += 1
                image_id_next += 1

    out_payload = {
        "images": out_images,
        "annotations": out_annotations,
        "categories": payload.get("categories", [{"id": 0, "name": "mosquito"}]),
    }
    ann_dir = output_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    (ann_dir / f"instances_{split}.json").write_text(
        json.dumps(out_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "split": split,
        "images": len(out_images),
        "annotations": len(out_annotations),
        "positive_tiles": positive_tiles,
        "negative_tiles": negative_tiles,
    }


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.overlap < 0.9:
        raise ValueError("--overlap must be in [0, 0.9)")
    if args.tile_size <= 0 or args.model_size <= 0:
        raise ValueError("--tile-size and --model-size must be positive")
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    splits = [
        build_split(
            dataset_dir=args.dataset_dir.resolve(),
            phone_frame_dir=args.phone_frame_dir.resolve() if args.phone_frame_dir else None,
            output_dir=args.output_dir.resolve(),
            split=split,
            tile_size=args.tile_size,
            overlap=args.overlap,
            model_size=args.model_size,
            min_visible_ratio=args.min_visible_ratio,
            negative_keep_prob=args.negative_keep_prob,
            rng=rng,
        )
        for split in args.splits
    ]
    summary = {
        "dataset_dir": str(args.dataset_dir.resolve()),
        "phone_frame_dir": str(args.phone_frame_dir.resolve()) if args.phone_frame_dir else None,
        "output_dir": str(args.output_dir.resolve()),
        "tile_size": args.tile_size,
        "overlap": args.overlap,
        "model_size": args.model_size,
        "min_visible_ratio": args.min_visible_ratio,
        "negative_keep_prob": args.negative_keep_prob,
        "splits": splits,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
