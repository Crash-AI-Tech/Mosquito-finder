#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


MODEL_SIZE = 416


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an aspect-preserving 416x416 letterbox COCO dataset from phone-frame COCO data."
    )
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--phone-frame-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["train2017", "val2017", "reality2017"])
    parser.add_argument("--clean", action="store_true")
    return parser


def source_box(annotation: dict[str, Any], image_meta: dict[str, Any]) -> tuple[float, float, float, float]:
    if "source_phone_box" in annotation:
        x, y, width, height = [float(value) for value in annotation["source_phone_box"]]
        return x, y, width, height

    source_width = float(image_meta.get("source_width", image_meta["width"]))
    source_height = float(image_meta.get("source_height", image_meta["height"]))
    x, y, width, height = [float(value) for value in annotation["bbox"]]
    return (
        x / float(image_meta["width"]) * source_width,
        y / float(image_meta["height"]) * source_height,
        width / float(image_meta["width"]) * source_width,
        height / float(image_meta["height"]) * source_height,
    )


def letterbox_image(image: Image.Image) -> tuple[Image.Image, float, int, int]:
    width, height = image.size
    scale = min(MODEL_SIZE / width, MODEL_SIZE / height)
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    resized = image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)
    canvas = Image.new("RGB", (MODEL_SIZE, MODEL_SIZE), (114, 114, 114))
    pad_x = (MODEL_SIZE - resized_width) // 2
    pad_y = (MODEL_SIZE - resized_height) // 2
    canvas.paste(resized, (pad_x, pad_y))
    return canvas, scale, pad_x, pad_y


def transform_box(box: tuple[float, float, float, float], scale: float, pad_x: int, pad_y: int) -> list[float]:
    x, y, width, height = box
    tx = x * scale + pad_x
    ty = y * scale + pad_y
    tw = width * scale
    th = height * scale
    tx = max(0.0, min(float(MODEL_SIZE - 1), tx))
    ty = max(0.0, min(float(MODEL_SIZE - 1), ty))
    tw = max(1.0, min(float(MODEL_SIZE) - tx, tw))
    th = max(1.0, min(float(MODEL_SIZE) - ty, th))
    return [round(tx, 3), round(ty, 3), round(tw, 3), round(th, 3)]


def build_split(dataset_dir: Path, phone_frame_dir: Path, output_dir: Path, split: str) -> dict[str, Any]:
    ann_path = dataset_dir / "annotations" / f"instances_{split}.json"
    if not ann_path.exists():
        return {"split": split, "skipped": True, "reason": "missing annotation file"}

    payload = json.loads(ann_path.read_text(encoding="utf-8"))
    images_by_id = {int(image["id"]): image for image in payload["images"]}
    annotations_by_image: dict[int, list[dict[str, Any]]] = {int(image["id"]): [] for image in payload["images"]}
    for annotation in payload["annotations"]:
        annotations_by_image.setdefault(int(annotation["image_id"]), []).append(annotation)

    out_image_dir = output_dir / split
    out_image_dir.mkdir(parents=True, exist_ok=True)
    out_images: list[dict[str, Any]] = []
    out_annotations: list[dict[str, Any]] = []
    ann_id = 1

    for image_meta in payload["images"]:
        image_id = int(image_meta["id"])
        phone_path = phone_frame_dir / split / str(image_meta["file_name"])
        if phone_path.exists():
            image = Image.open(phone_path).convert("RGB")
        else:
            image = Image.open(dataset_dir / split / str(image_meta["file_name"])).convert("RGB")
        letterboxed, scale, pad_x, pad_y = letterbox_image(image)
        letterboxed.save(out_image_dir / str(image_meta["file_name"]), quality=92)

        out_meta = {
            **image_meta,
            "width": MODEL_SIZE,
            "height": MODEL_SIZE,
            "letterbox": True,
            "letterbox_scale": scale,
            "letterbox_pad_x": pad_x,
            "letterbox_pad_y": pad_y,
            "source_width": image.width,
            "source_height": image.height,
        }
        out_images.append(out_meta)

        for annotation in annotations_by_image.get(image_id, []):
            bbox = transform_box(source_box(annotation, image_meta), scale, pad_x, pad_y)
            out_annotations.append(
                {
                    **annotation,
                    "id": ann_id,
                    "bbox": bbox,
                    "area": round(bbox[2] * bbox[3], 3),
                    "letterboxed": True,
                }
            )
            ann_id += 1

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
    }


def main() -> int:
    args = build_parser().parse_args()
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    splits = [
        build_split(args.dataset_dir.resolve(), args.phone_frame_dir.resolve(), args.output_dir.resolve(), split)
        for split in args.splits
    ]
    summary = {
        "dataset_dir": str(args.dataset_dir.resolve()),
        "phone_frame_dir": str(args.phone_frame_dir.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "model_size": MODEL_SIZE,
        "splits": splits,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
