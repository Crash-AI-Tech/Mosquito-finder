#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "external" / "huggingface_mosquito_species"
DEFAULT_YOLO_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "huggingface_mosquito_yolo_single_class"
DEFAULT_COCO_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "huggingface_mosquito_coco_single_class"
CLASS_NAME = "mosquito"


@dataclass(frozen=True)
class PreparedBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def as_coco_bbox(self) -> list[float]:
        return [
            round(self.x_min, 3),
            round(self.y_min, 3),
            round(self.x_max - self.x_min, 3),
            round(self.y_max - self.y_min, 3),
        ]

    def as_yolo_row(self, image_width: int, image_height: int) -> str:
        width = self.x_max - self.x_min
        height = self.y_max - self.y_min
        center_x = self.x_min + width / 2
        center_y = self.y_min + height / 2
        return (
            f"0 {center_x / image_width:.6f} {center_y / image_height:.6f} "
            f"{width / image_width:.6f} {height / image_height:.6f}"
        )


@dataclass(frozen=True)
class PreparedSample:
    split: str
    source_file: str
    output_file: str
    species: str
    image_bytes: bytes
    image_width: int
    image_height: int
    boxes: list[PreparedBox]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare single-class YOLO and COCO datasets from Hugging Face mosquito detection parquet files."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--yolo-output-dir", type=Path, default=DEFAULT_YOLO_OUTPUT_DIR)
    parser.add_argument("--coco-output-dir", type=Path, default=DEFAULT_COCO_OUTPUT_DIR)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--clean", action="store_true")
    return parser


def split_for_filename(filename: str, val_ratio: float) -> str:
    bucket = int(hashlib.sha1(filename.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_ratio else "train"


def clip_box(raw_box: list[float], image_width: int, image_height: int) -> PreparedBox | None:
    if len(raw_box) != 4:
        return None
    x_min, y_min, x_max, y_max = [float(value) for value in raw_box]
    x_min = max(0.0, min(x_min, float(image_width)))
    y_min = max(0.0, min(y_min, float(image_height)))
    x_max = max(0.0, min(x_max, float(image_width)))
    y_max = max(0.0, min(y_max, float(image_height)))
    if x_max <= x_min or y_max <= y_min:
        return None
    return PreparedBox(x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max)


def unique_output_name(filename: str, seen_names: Counter[str]) -> str:
    seen_names[filename] += 1
    if seen_names[filename] == 1:
        return filename
    path = Path(filename)
    return f"{path.stem}_{seen_names[filename]}{path.suffix}"


def iter_samples(source_dir: Path, val_ratio: float) -> tuple[list[PreparedSample], dict[str, Any]]:
    parquet_files = sorted((source_dir / "data").glob("train-*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found under {source_dir / 'data'}")

    samples: list[PreparedSample] = []
    skipped: list[dict[str, str]] = []
    species_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    seen_names: Counter[str] = Counter()

    for parquet_file in parquet_files:
        table = pq.read_table(parquet_file, columns=["image", "filename", "label", "objects"])
        for row_index, row in enumerate(table.to_pylist()):
            filename = row.get("filename") or f"{parquet_file.stem}_{row_index}.jpg"
            image = row.get("image") or {}
            image_bytes = image.get("bytes")
            species = row.get("label") or "unknown"
            objects = row.get("objects") or {}
            raw_boxes = objects.get("bboxes") or []

            if not image_bytes:
                skipped.append({"file": filename, "reason": "missing_image_bytes"})
                continue
            if not raw_boxes:
                skipped.append({"file": filename, "reason": "missing_boxes"})
                continue

            try:
                with Image.open(BytesIO(image_bytes)) as pil_image:
                    image_width, image_height = pil_image.size
                    pil_image.verify()
            except Exception as exc:  # noqa: BLE001
                skipped.append({"file": filename, "reason": "invalid_image", "detail": str(exc)})
                continue

            boxes = [
                clipped_box
                for raw_box in raw_boxes
                if (clipped_box := clip_box(raw_box, image_width, image_height)) is not None
            ]
            if not boxes:
                skipped.append({"file": filename, "reason": "invalid_boxes"})
                continue

            split = split_for_filename(filename, val_ratio)
            output_file = unique_output_name(filename, seen_names)
            samples.append(
                PreparedSample(
                    split=split,
                    source_file=filename,
                    output_file=output_file,
                    species=species,
                    image_bytes=image_bytes,
                    image_width=image_width,
                    image_height=image_height,
                    boxes=boxes,
                )
            )
            species_counts[species] += 1
            split_counts[split] += 1

    metadata = {
        "source_dir": str(source_dir),
        "source_format": "huggingface_parquet",
        "source_license": "CC-BY-SA-4.0",
        "class_name": CLASS_NAME,
        "class_mapping": "all_species_to_single_mosquito_class",
        "species_counts": dict(sorted(species_counts.items())),
        "skipped": skipped,
        "splits": dict(sorted(split_counts.items())),
    }
    return samples, metadata


def reset_output_dir(path: Path, clean: bool) -> None:
    if clean and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_yolo_dataset(samples: list[PreparedSample], metadata: dict[str, Any], output_dir: Path, clean: bool) -> None:
    reset_output_dir(output_dir, clean)
    manifest: list[dict[str, Any]] = []
    split_counts: dict[str, dict[str, int]] = {}

    for sample in samples:
        image_dir = output_dir / "images" / sample.split
        label_dir = output_dir / "labels" / sample.split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)

        image_path = image_dir / sample.output_file
        label_path = label_dir / f"{Path(sample.output_file).stem}.txt"
        image_path.write_bytes(sample.image_bytes)
        label_path.write_text(
            "\n".join(box.as_yolo_row(sample.image_width, sample.image_height) for box in sample.boxes) + "\n",
            encoding="utf-8",
        )

        split_summary = split_counts.setdefault(sample.split, {"images": 0, "boxes": 0})
        split_summary["images"] += 1
        split_summary["boxes"] += len(sample.boxes)
        manifest.append(
            {
                "split": sample.split,
                "source_file": sample.source_file,
                "output_image": str(image_path.relative_to(REPO_ROOT)),
                "output_label": str(label_path.relative_to(REPO_ROOT)),
                "species": sample.species,
                "width": sample.image_width,
                "height": sample.image_height,
                "boxes": len(sample.boxes),
            }
        )

    dataset_yaml = "\n".join(
        [
            f"path: {output_dir}",
            "train: images/train",
            "val: images/val",
            "names:",
            f"  0: {CLASS_NAME}",
            "",
        ]
    )
    (output_dir / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")
    write_json(output_dir / "manifest.json", {"samples": manifest})
    write_json(output_dir / "summary.json", {**metadata, "format": "yolo", "splits": split_counts})


def write_coco_dataset(samples: list[PreparedSample], metadata: dict[str, Any], output_dir: Path, clean: bool) -> None:
    reset_output_dir(output_dir, clean)
    annotations_dir = output_dir / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    split_counts: dict[str, dict[str, int]] = {}

    for split in ("train", "val"):
        split_samples = [sample for sample in samples if sample.split == split]
        coco_split = "train2017" if split == "train" else "val2017"
        image_dir = output_dir / coco_split
        image_dir.mkdir(parents=True, exist_ok=True)

        coco_images: list[dict[str, Any]] = []
        coco_annotations: list[dict[str, Any]] = []
        annotation_id = 1
        for image_id, sample in enumerate(split_samples, 1):
            image_path = image_dir / sample.output_file
            image_path.write_bytes(sample.image_bytes)
            coco_images.append(
                {
                    "id": image_id,
                    "file_name": sample.output_file,
                    "width": sample.image_width,
                    "height": sample.image_height,
                    "species": sample.species,
                    "source_file": sample.source_file,
                }
            )
            for box in sample.boxes:
                bbox = box.as_coco_bbox()
                coco_annotations.append(
                    {
                        "id": annotation_id,
                        "image_id": image_id,
                        "category_id": 0,
                        "bbox": bbox,
                        "area": round(bbox[2] * bbox[3], 3),
                        "iscrowd": 0,
                    }
                )
                annotation_id += 1

        payload = {
            "images": coco_images,
            "annotations": coco_annotations,
            "categories": [{"id": 0, "name": CLASS_NAME, "supercategory": "insect"}],
        }
        write_json(annotations_dir / f"instances_{coco_split}.json", payload)
        split_counts[split] = {"images": len(coco_images), "boxes": len(coco_annotations)}

    write_json(output_dir / "summary.json", {**metadata, "format": "coco", "splits": split_counts})


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    if not 0.0 < args.val_ratio < 1.0:
        raise ValueError("--val-ratio must be between 0 and 1")

    samples, metadata = iter_samples(args.source_dir, args.val_ratio)
    write_yolo_dataset(samples, metadata, args.yolo_output_dir, args.clean)
    write_coco_dataset(samples, metadata, args.coco_output_dir, args.clean)

    print(f"YOLO dataset written to: {args.yolo_output_dir}")
    print(f"COCO dataset written to: {args.coco_output_dir}")
    print(f"Prepared samples: {len(samples)}")
    print(f"Skipped samples: {len(metadata['skipped'])}")
    print(f"Splits: {metadata['splits']}")


if __name__ == "__main__":
    main()
