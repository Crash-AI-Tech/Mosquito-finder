#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "external" / "kaggle_low_light_mosquito" / "dataset"
DEFAULT_YOLO_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "kaggle_yolo_single_class"
DEFAULT_COCO_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "kaggle_coco_single_class"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CLASS_NAME = "mosquito"


@dataclass(frozen=True)
class YoloBox:
    original_class_id: int
    center_x: float
    center_y: float
    width: float
    height: float

    def as_single_class_yolo(self) -> str:
        return f"0 {self.center_x:.6f} {self.center_y:.6f} {self.width:.6f} {self.height:.6f}"

    def as_coco_bbox(self, image_width: int, image_height: int) -> list[float]:
        x = (self.center_x - self.width / 2) * image_width
        y = (self.center_y - self.height / 2) * image_height
        return [
            round(x, 3),
            round(y, 3),
            round(self.width * image_width, 3),
            round(self.height * image_height, 3),
        ]


@dataclass(frozen=True)
class PreparedSample:
    split: str
    image_path: Path
    label_path: Path
    boxes: list[YoloBox]
    image_width: int
    image_height: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare clean single-class YOLO and COCO datasets from Kaggle low-light mosquito data."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--yolo-output-dir", type=Path, default=DEFAULT_YOLO_OUTPUT_DIR)
    parser.add_argument("--coco-output-dir", type=Path, default=DEFAULT_COCO_OUTPUT_DIR)
    parser.add_argument("--clean", action="store_true")
    return parser


def parse_label_file(path: Path) -> tuple[list[YoloBox], list[str]]:
    boxes: list[YoloBox] = []
    errors: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            errors.append(f"{path}:{line_number}: expected 5 columns, got {len(parts)}")
            continue
        try:
            class_id = int(parts[0])
            center_x, center_y, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            errors.append(f"{path}:{line_number}: non-numeric field")
            continue
        values = [center_x, center_y, width, height]
        if class_id < 0:
            errors.append(f"{path}:{line_number}: negative class id {class_id}")
            continue
        if any(value < 0.0 or value > 1.0 for value in values):
            errors.append(f"{path}:{line_number}: normalized box value outside [0, 1]")
            continue
        if width <= 0.0 or height <= 0.0:
            errors.append(f"{path}:{line_number}: non-positive box width or height")
            continue
        boxes.append(YoloBox(class_id, center_x, center_y, width, height))
    return boxes, errors


def image_paths_for_split(source_dir: Path, split: str) -> list[Path]:
    image_dir = source_dir / "train_dark" / "images" / split
    if not image_dir.exists():
        return []
    return sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)


def load_samples(source_dir: Path) -> tuple[list[PreparedSample], dict[str, Any]]:
    samples: list[PreparedSample] = []
    skipped: list[dict[str, str]] = []
    original_class_counts: dict[str, int] = {}

    for split in ("train", "val"):
        for image_path in image_paths_for_split(source_dir, split):
            label_path = source_dir / "train_dark" / "labels" / split / f"{image_path.stem}.txt"
            if not label_path.exists():
                skipped.append(
                    {
                        "split": split,
                        "image": str(image_path.relative_to(source_dir)),
                        "reason": "missing_label",
                    }
                )
                continue

            boxes, label_errors = parse_label_file(label_path)
            if label_errors:
                skipped.append(
                    {
                        "split": split,
                        "image": str(image_path.relative_to(source_dir)),
                        "label": str(label_path.relative_to(source_dir)),
                        "reason": "invalid_label",
                        "detail": "; ".join(label_errors),
                    }
                )
                continue
            if not boxes:
                skipped.append(
                    {
                        "split": split,
                        "image": str(image_path.relative_to(source_dir)),
                        "label": str(label_path.relative_to(source_dir)),
                        "reason": "empty_label",
                    }
                )
                continue

            with Image.open(image_path) as image:
                image_width, image_height = image.size

            for box in boxes:
                key = str(box.original_class_id)
                original_class_counts[key] = original_class_counts.get(key, 0) + 1

            samples.append(
                PreparedSample(
                    split=split,
                    image_path=image_path,
                    label_path=label_path,
                    boxes=boxes,
                    image_width=image_width,
                    image_height=image_height,
                )
            )

    metadata = {
        "source_dir": str(source_dir),
        "class_name": CLASS_NAME,
        "class_mapping": "all_original_classes_to_single_mosquito_class",
        "original_class_counts": dict(sorted(original_class_counts.items(), key=lambda item: int(item[0]))),
        "skipped": skipped,
    }
    return samples, metadata


def reset_output_dir(path: Path, clean: bool) -> None:
    if clean and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_yolo_dataset(samples: list[PreparedSample], metadata: dict[str, Any], output_dir: Path, clean: bool) -> None:
    reset_output_dir(output_dir, clean)
    split_counts: dict[str, dict[str, int]] = {}
    manifest: list[dict[str, Any]] = []

    for sample in samples:
        image_output_dir = output_dir / "images" / sample.split
        label_output_dir = output_dir / "labels" / sample.split
        image_output_dir.mkdir(parents=True, exist_ok=True)
        label_output_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(sample.image_path, image_output_dir / sample.image_path.name)
        label_rows = [box.as_single_class_yolo() for box in sample.boxes]
        (label_output_dir / f"{sample.image_path.stem}.txt").write_text(
            "\n".join(label_rows) + "\n",
            encoding="utf-8",
        )

        split_summary = split_counts.setdefault(sample.split, {"images": 0, "boxes": 0})
        split_summary["images"] += 1
        split_summary["boxes"] += len(sample.boxes)
        manifest.append(
            {
                "split": sample.split,
                "source_image": str(sample.image_path.relative_to(REPO_ROOT)),
                "source_label": str(sample.label_path.relative_to(REPO_ROOT)),
                "output_image": str((image_output_dir / sample.image_path.name).relative_to(REPO_ROOT)),
                "output_label": str((label_output_dir / f"{sample.image_path.stem}.txt").relative_to(REPO_ROOT)),
                "boxes": len(sample.boxes),
                "width": sample.image_width,
                "height": sample.image_height,
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
        image_output_dir = output_dir / coco_split
        image_output_dir.mkdir(parents=True, exist_ok=True)

        coco_images: list[dict[str, Any]] = []
        coco_annotations: list[dict[str, Any]] = []
        annotation_id = 1
        for image_id, sample in enumerate(split_samples, 1):
            output_image = image_output_dir / sample.image_path.name
            shutil.copy2(sample.image_path, output_image)
            coco_images.append(
                {
                    "id": image_id,
                    "file_name": sample.image_path.name,
                    "width": sample.image_width,
                    "height": sample.image_height,
                }
            )
            for box in sample.boxes:
                bbox = box.as_coco_bbox(sample.image_width, sample.image_height)
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
    samples, metadata = load_samples(args.source_dir)
    write_yolo_dataset(samples, metadata, args.yolo_output_dir, args.clean)
    write_coco_dataset(samples, metadata, args.coco_output_dir, args.clean)
    print(f"YOLO dataset written to: {args.yolo_output_dir}")
    print(f"COCO dataset written to: {args.coco_output_dir}")
    print(f"Prepared samples: {len(samples)}")
    print(f"Skipped samples: {len(metadata['skipped'])}")


if __name__ == "__main__":
    main()
