#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "combined_mosquito_coco_single_class"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge single-class COCO detection datasets.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dataset", action="append", required=True, help="name=path pair, repeatable.")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--copy-images", action="store_true", help="Copy images instead of symlinking.")
    return parser


def parse_dataset_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Expected name=path dataset argument, got: {value}")
    name, raw_path = value.split("=", 1)
    return sanitize_name(name), Path(raw_path).resolve()


def sanitize_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "dataset"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def link_or_copy(source: Path, target: Path, copy_images: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    source = source.resolve()
    if copy_images:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source)


def source_split_dir(dataset_dir: Path, coco_split: str) -> Path:
    path = dataset_dir / coco_split
    if path.exists():
        return path
    raise FileNotFoundError(path)


def merge_split(
    datasets: list[tuple[str, Path]],
    output_dir: Path,
    split: str,
    copy_images: bool,
) -> dict[str, Any]:
    coco_split = "train2017" if split == "train" else "val2017"
    output_images_dir = output_dir / coco_split
    output_images_dir.mkdir(parents=True, exist_ok=True)

    merged_images: list[dict[str, Any]] = []
    merged_annotations: list[dict[str, Any]] = []
    source_counts: dict[str, dict[str, int]] = {}
    next_image_id = 1
    next_annotation_id = 1

    for source_name, dataset_dir in datasets:
        ann_path = dataset_dir / "annotations" / f"instances_{coco_split}.json"
        payload = read_json(ann_path)
        images_by_id = {int(image["id"]): image for image in payload["images"]}
        annotations_by_image: dict[int, list[dict[str, Any]]] = {}
        for annotation in payload["annotations"]:
            annotations_by_image.setdefault(int(annotation["image_id"]), []).append(annotation)

        image_count = 0
        annotation_count = 0
        for original_image_id, image in images_by_id.items():
            source_image_path = source_split_dir(dataset_dir, coco_split) / str(image["file_name"])
            output_file_name = f"{source_name}_{image['file_name']}"
            output_image_path = output_images_dir / output_file_name
            link_or_copy(source_image_path, output_image_path, copy_images)

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

            for annotation in annotations_by_image.get(original_image_id, []):
                merged_annotations.append(
                    {
                        **annotation,
                        "id": next_annotation_id,
                        "image_id": next_image_id,
                        "category_id": 0,
                    }
                )
                next_annotation_id += 1
                annotation_count += 1
            next_image_id += 1

        source_counts[source_name] = {"images": image_count, "boxes": annotation_count}

    write_json(
        output_dir / "annotations" / f"instances_{coco_split}.json",
        {
            "images": merged_images,
            "annotations": merged_annotations,
            "categories": [{"id": 0, "name": "mosquito", "supercategory": "insect"}],
        },
    )
    return {
        "images": len(merged_images),
        "boxes": len(merged_annotations),
        "sources": source_counts,
    }


def main() -> None:
    args = build_parser().parse_args()
    datasets = [parse_dataset_arg(value) for value in args.dataset]
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "output_dir": str(args.output_dir),
        "format": "coco",
        "class_name": "mosquito",
        "image_storage": "copy" if args.copy_images else "symlink",
        "datasets": {name: str(path) for name, path in datasets},
        "splits": {
            "train": merge_split(datasets, args.output_dir, "train", args.copy_images),
            "val": merge_split(datasets, args.output_dir, "val", args.copy_images),
        },
    }
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
