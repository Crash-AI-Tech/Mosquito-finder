#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "real_detector_mix_coco"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a COCO detector mix with separate train/val sources and pseudo-label filtering."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-source", action="append", required=True, help="name=dataset_dir, repeatable.")
    parser.add_argument("--val-source", action="append", required=True, help="name=dataset_dir, repeatable.")
    parser.add_argument(
        "--train-negative-source",
        action="append",
        default=[],
        help="name=dataset_dir with COCO images but no mosquito boxes, repeatable.",
    )
    parser.add_argument(
        "--val-negative-source",
        action="append",
        default=[],
        help="name=dataset_dir with COCO images but no mosquito boxes, repeatable.",
    )
    parser.add_argument("--min-pseudo-score", type=float, default=0.0)
    parser.add_argument(
        "--min-box-size",
        type=float,
        default=4.0,
        help="Drop boxes smaller than this many source-image pixels after clipping.",
    )
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument(
        "--normalize-images",
        action="store_true",
        help="Write EXIF-transposed image copies when file pixels do not match COCO metadata.",
    )
    parser.add_argument("--clean", action="store_true")
    return parser


def parse_source(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Expected name=path source, got: {value}")
    raw_name, raw_path = value.split("=", 1)
    name = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw_name).strip("_")
    return name or "dataset", Path(raw_path).resolve()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_normalized_image(source: Path, target: Path, expected_width: int, expected_height: int) -> bool:
    with Image.open(source) as image:
        expected_size = (expected_width, expected_height)
        orientation = image.getexif().get(274)
        if image.size == expected_size and orientation in (None, 0, 1):
            return False
        if image.size == expected_size:
            normalized = image.copy()
        else:
            normalized = ImageOps.exif_transpose(image)
            if normalized.size != expected_size:
                return False
        target.parent.mkdir(parents=True, exist_ok=True)
        save_image = normalized
        if target.suffix.lower() in {".jpg", ".jpeg"} and save_image.mode not in {"RGB", "L"}:
            save_image = save_image.convert("RGB")
        save_kwargs: dict[str, Any] = {}
        if target.suffix.lower() in {".jpg", ".jpeg"}:
            save_kwargs = {"quality": 95}
        save_image.save(target, **save_kwargs)
        return True


def link_or_copy(
    source: Path,
    target: Path,
    copy_images: bool,
    normalize_images: bool,
    expected_width: int,
    expected_height: int,
) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if normalize_images and write_normalized_image(source, target, expected_width, expected_height):
        return True
    if copy_images:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source.resolve())
    return False


def source_image_path(dataset_dir: Path, coco_split: str, file_name: str) -> Path:
    path = dataset_dir / coco_split / file_name
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def normalized_annotation(
    annotation: dict[str, Any],
    image: dict[str, Any],
    min_pseudo_score: float,
    min_box_size: float,
) -> dict[str, Any] | None:
    if annotation.get("pseudo") and float(annotation.get("score", 0.0)) < min_pseudo_score:
        return None

    image_width = float(image["width"])
    image_height = float(image["height"])
    x, y, width, height = [float(value) for value in annotation["bbox"]]
    x1 = max(0.0, x)
    y1 = max(0.0, y)
    x2 = min(image_width, x + width)
    y2 = min(image_height, y + height)
    clipped_width = x2 - x1
    clipped_height = y2 - y1
    if clipped_width < min_box_size or clipped_height < min_box_size:
        return None

    normalized = {
        **annotation,
        "bbox": [
            round(x1, 3),
            round(y1, 3),
            round(clipped_width, 3),
            round(clipped_height, 3),
        ],
        "area": round(clipped_width * clipped_height, 3),
    }
    if x1 != x or y1 != y or clipped_width != width or clipped_height != height:
        normalized["bbox_clipped"] = True
    return normalized


def merge_sources(
    sources: list[tuple[str, Path]],
    negative_sources: list[tuple[str, Path]],
    output_dir: Path,
    output_split: str,
    input_split: str,
    copy_images: bool,
    normalize_images: bool,
    min_pseudo_score: float,
    min_box_size: float,
) -> dict[str, Any]:
    output_images_dir = output_dir / output_split
    merged_images: list[dict[str, Any]] = []
    merged_annotations: list[dict[str, Any]] = []
    source_counts: dict[str, dict[str, int]] = {}
    next_image_id = 1
    next_annotation_id = 1

    for source_name, dataset_dir in sources:
        ann_path = dataset_dir / "annotations" / f"instances_{input_split}.json"
        payload = read_json(ann_path)
        images_by_id = {int(image["id"]): image for image in payload.get("images", [])}
        annotations_by_image: dict[int, list[dict[str, Any]]] = {}
        skipped_boxes_after_filter = 0
        clipped_boxes = 0
        for annotation in payload.get("annotations", []):
            image = images_by_id[int(annotation["image_id"])]
            normalized = normalized_annotation(annotation, image, min_pseudo_score, min_box_size)
            if normalized is None:
                skipped_boxes_after_filter += 1
                continue
            if normalized.get("bbox_clipped"):
                clipped_boxes += 1
            annotations_by_image.setdefault(int(annotation["image_id"]), []).append(normalized)

        image_count = 0
        box_count = 0
        skipped_without_boxes = 0
        normalized_images = 0
        for image in payload.get("images", []):
            source_annotations = annotations_by_image.get(int(image["id"]), [])
            if not source_annotations:
                skipped_without_boxes += 1
                continue

            output_file_name = f"{source_name}_{image['file_name']}"
            if link_or_copy(
                source_image_path(dataset_dir, input_split, str(image["file_name"])),
                output_images_dir / output_file_name,
                copy_images,
                normalize_images,
                int(image["width"]),
                int(image["height"]),
            ):
                normalized_images += 1

            merged_images.append(
                {
                    **image,
                    "id": next_image_id,
                    "file_name": output_file_name,
                    "source_dataset": source_name,
                    "source_file_name": image["file_name"],
                }
            )
            image_count += 1

            for annotation in source_annotations:
                merged_annotations.append(
                    {
                        **annotation,
                        "id": next_annotation_id,
                        "image_id": next_image_id,
                        "category_id": 0,
                    }
                )
                next_annotation_id += 1
                box_count += 1
            next_image_id += 1

        source_counts[source_name] = {
            "images": image_count,
            "boxes": box_count,
            "skipped_images_without_boxes_after_filter": skipped_without_boxes,
            "skipped_boxes_after_filter": skipped_boxes_after_filter,
            "clipped_boxes": clipped_boxes,
            "normalized_images": normalized_images,
        }

    negative_source_counts: dict[str, dict[str, int]] = {}
    for source_name, dataset_dir in negative_sources:
        ann_path = dataset_dir / "annotations" / f"instances_{input_split}.json"
        payload = read_json(ann_path)
        image_count = 0
        skipped_with_boxes = 0
        normalized_images = 0
        annotations_by_image: dict[int, int] = {}
        for annotation in payload.get("annotations", []):
            annotations_by_image[int(annotation["image_id"])] = annotations_by_image.get(int(annotation["image_id"]), 0) + 1

        for image in payload.get("images", []):
            if annotations_by_image.get(int(image["id"]), 0) > 0:
                skipped_with_boxes += 1
                continue

            output_file_name = f"{source_name}_{image['file_name']}"
            if link_or_copy(
                source_image_path(dataset_dir, input_split, str(image["file_name"])),
                output_images_dir / output_file_name,
                copy_images,
                normalize_images,
                int(image["width"]),
                int(image["height"]),
            ):
                normalized_images += 1

            merged_images.append(
                {
                    **image,
                    "id": next_image_id,
                    "file_name": output_file_name,
                    "source_dataset": source_name,
                    "source_file_name": image["file_name"],
                    "negative_only": True,
                }
            )
            next_image_id += 1
            image_count += 1

        negative_source_counts[source_name] = {
            "images": image_count,
            "boxes": 0,
            "skipped_images_with_boxes": skipped_with_boxes,
            "normalized_images": normalized_images,
        }

    write_json(
        output_dir / "annotations" / f"instances_{output_split}.json",
        {
            "images": merged_images,
            "annotations": merged_annotations,
            "categories": [{"id": 0, "name": "mosquito", "supercategory": "insect"}],
        },
    )
    return {
        "images": len(merged_images),
        "boxes": len(merged_annotations),
        "positive_sources": source_counts,
        "negative_sources": negative_source_counts,
    }


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    train_sources = [parse_source(value) for value in args.train_source]
    val_sources = [parse_source(value) for value in args.val_source]
    train_negative_sources = [parse_source(value) for value in args.train_negative_source]
    val_negative_sources = [parse_source(value) for value in args.val_negative_source]

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "output_dir": str(output_dir),
        "format": "coco",
        "class_name": "mosquito",
        "image_storage": "copy" if args.copy_images else "symlink",
        "normalize_images": args.normalize_images,
        "min_pseudo_score": args.min_pseudo_score,
        "min_box_size": args.min_box_size,
        "train_sources": {name: str(path) for name, path in train_sources},
        "val_sources": {name: str(path) for name, path in val_sources},
        "train_negative_sources": {name: str(path) for name, path in train_negative_sources},
        "val_negative_sources": {name: str(path) for name, path in val_negative_sources},
        "splits": {
            "train": merge_sources(
                train_sources,
                train_negative_sources,
                output_dir,
                "train2017",
                "train2017",
                args.copy_images,
                args.normalize_images,
                args.min_pseudo_score,
                args.min_box_size,
            ),
            "val": merge_sources(
                val_sources,
                val_negative_sources,
                output_dir,
                "val2017",
                "val2017",
                args.copy_images,
                args.normalize_images,
                args.min_pseudo_score,
                args.min_box_size,
            ),
        },
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
