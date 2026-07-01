#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "hard_negative_coco"
DEFAULT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a COCO dataset of mosquito-free hard negative images."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="name=directory, repeatable. All images are treated as mosquito-free.",
    )
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--max-images-per-source", type=int, default=None)
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument(
        "--normalize-images",
        action="store_true",
        help="Write EXIF-transposed RGB image copies instead of linking raw files.",
    )
    parser.add_argument("--clean", action="store_true")
    return parser


def parse_source(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"Expected name=path, got: {value}")
    raw_name, raw_path = value.split("=", 1)
    name = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw_name).strip("_")
    if not name:
        raise ValueError(f"Invalid source name: {value}")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return name, path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def image_files(root: Path) -> list[Path]:
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in DEFAULT_EXTENSIONS
    ]
    return sorted(files)


def stable_split(source_name: str, path: Path, val_ratio: float, seed: int) -> str:
    digest = hashlib.sha1(f"{seed}:{source_name}:{path.as_posix()}".encode("utf-8")).hexdigest()
    value = int(digest[:8], 16) / 0xFFFFFFFF
    return "val2017" if value < val_ratio else "train2017"


def output_name(source_name: str, source_root: Path, image_path: Path) -> str:
    relative = image_path.relative_to(source_root)
    stem = "_".join(relative.with_suffix("").parts)
    digest = hashlib.sha1(str(relative).encode("utf-8")).hexdigest()[:10]
    suffix = image_path.suffix.lower()
    if suffix in {".heic", ".heif", ".webp"}:
        suffix = ".jpg"
    return f"{source_name}_{stem}_{digest}{suffix}"


def write_or_link_image(
    source: Path,
    target: Path,
    copy_images: bool,
    normalize_images: bool,
) -> tuple[int, int, bool]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()

    with Image.open(source) as opened:
        normalized = ImageOps.exif_transpose(opened)
        width, height = normalized.size
        should_write = normalize_images or source.suffix.lower() in {".heic", ".heif", ".webp"}
        if should_write:
            image = normalized.convert("RGB")
            image.save(target, quality=95)
            return width, height, True

    if copy_images:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source)
    return width, height, False


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    sources = [parse_source(value) for value in args.source]
    rng = random.Random(args.seed)

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)

    images_by_split: dict[str, list[dict[str, Any]]] = {"train2017": [], "val2017": []}
    source_summary: dict[str, dict[str, int]] = {}
    next_ids = {"train2017": 1, "val2017": 1}

    for source_name, source_root in sources:
        files = image_files(source_root)
        if args.max_images_per_source is not None and len(files) > args.max_images_per_source:
            files = rng.sample(files, args.max_images_per_source)
            files.sort()

        counts = {
            "seen": len(files),
            "train2017": 0,
            "val2017": 0,
            "skipped_unreadable": 0,
            "normalized_images": 0,
        }

        for image_path in files:
            split = stable_split(source_name, image_path.relative_to(source_root), args.val_ratio, args.seed)
            file_name = output_name(source_name, source_root, image_path)
            target = output_dir / split / file_name
            try:
                width, height, normalized = write_or_link_image(
                    image_path,
                    target,
                    copy_images=args.copy_images,
                    normalize_images=args.normalize_images,
                )
            except Exception as error:
                counts["skipped_unreadable"] += 1
                print(f"skip unreadable image: {image_path} ({error})")
                continue

            images_by_split[split].append(
                {
                    "id": next_ids[split],
                    "file_name": file_name,
                    "width": width,
                    "height": height,
                    "source_dataset": source_name,
                    "source_file_name": image_path.relative_to(source_root).as_posix(),
                    "negative_only": True,
                }
            )
            next_ids[split] += 1
            counts[split] += 1
            if normalized:
                counts["normalized_images"] += 1

        source_summary[source_name] = counts

    for split, images in images_by_split.items():
        write_json(
            output_dir / "annotations" / f"instances_{split}.json",
            {
                "images": images,
                "annotations": [],
                "categories": [{"id": 0, "name": "mosquito", "supercategory": "insect"}],
            },
        )

    summary = {
        "output_dir": str(output_dir),
        "format": "coco_empty_annotations",
        "class_name": "mosquito",
        "image_storage": "copy" if args.copy_images or args.normalize_images else "symlink",
        "val_ratio": args.val_ratio,
        "seed": args.seed,
        "sources": {name: str(path) for name, path in sources},
        "source_counts": source_summary,
        "splits": {
            split: {"images": len(images), "boxes": 0}
            for split, images in images_by_split.items()
        },
    }
    write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
