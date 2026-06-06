#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "external" / "mosquito_alert_tigapics"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "mosquito_alert_species_classification"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MANIFEST_FIELDS = [
    "split",
    "class_name",
    "confidence",
    "report_id",
    "date",
    "location",
    "source_path",
    "output_path",
    "width",
    "height",
    "size",
]


@dataclass(frozen=True)
class PreparedSample:
    split: str
    class_name: str
    confidence: str
    report_id: str
    date: str
    location: str
    source_path: Path
    output_path: Path
    width: int
    height: int
    size: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare Mosquito Alert Tigapics as an image-level species classification dataset."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help="Copy images instead of creating symlinks. This roughly doubles dataset storage.",
    )
    return parser


def attrs_by_name(item: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for attr in item.get("attributes") or []:
        name = str(attr.get("name") or "")
        value = str(attr.get("value") or "")
        if name:
            values[name] = value
    return values


def split_for_key(key: str, val_ratio: float) -> str:
    bucket = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_ratio else "train"


def clean_class_name(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return normalized or "unknown"


def unique_output_name(relative_path: str) -> str:
    path = Path(relative_path)
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:10]
    return f"{path.stem}_{digest}{path.suffix.lower()}"


def reset_output_dir(path: Path, clean: bool) -> None:
    if clean and path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def link_or_copy(source: Path, target: Path, copy_images: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if copy_images:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source)


def load_file_items(source_dir: Path) -> list[dict[str, Any]]:
    file_list = source_dir / "labels" / "File_List.json"
    items = json.loads(file_list.read_text(encoding="utf-8"))
    return [item for item in items if item.get("type") == "file" and item.get("path")]


def prepare_samples(source_dir: Path, output_dir: Path, val_ratio: float, copy_images: bool) -> tuple[list[PreparedSample], dict[str, Any]]:
    samples: list[PreparedSample] = []
    skipped: list[dict[str, str]] = []
    class_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    split_counts: dict[str, Counter[str]] = {"train": Counter(), "val": Counter()}

    for item in load_file_items(source_dir):
        relative_path = str(item["path"])
        source_path = source_dir / "images" / relative_path
        expected_size = int(item.get("size") or 0)
        if source_path.suffix.lower() not in IMAGE_EXTENSIONS:
            skipped.append({"path": relative_path, "reason": "unsupported_extension"})
            continue
        if not source_path.exists():
            skipped.append({"path": relative_path, "reason": "missing_file"})
            continue
        actual_size = source_path.stat().st_size
        if expected_size and actual_size != expected_size:
            skipped.append({"path": relative_path, "reason": "size_mismatch"})
            continue

        metadata = attrs_by_name(item)
        class_name = clean_class_name(metadata.get("class") or Path(relative_path).parent.name)
        split = split_for_key(metadata.get("report_id") or relative_path, val_ratio)
        output_name = unique_output_name(relative_path)
        output_path = output_dir / "images" / split / class_name / output_name

        try:
            with Image.open(source_path) as image:
                width, height = image.size
                image.verify()
        except Exception as exc:  # noqa: BLE001
            skipped.append({"path": relative_path, "reason": "invalid_image", "detail": str(exc)})
            continue

        link_or_copy(source_path, output_path, copy_images)
        sample = PreparedSample(
            split=split,
            class_name=class_name,
            confidence=metadata.get("confidence", ""),
            report_id=metadata.get("report_id", ""),
            date=metadata.get("date", ""),
            location=metadata.get("location", ""),
            source_path=source_path,
            output_path=output_path,
            width=width,
            height=height,
            size=actual_size,
        )
        samples.append(sample)
        class_counts[class_name] += 1
        confidence_counts[sample.confidence] += 1
        split_counts[split][class_name] += 1

    summary = {
        "source_dir": str(source_dir),
        "source_format": "Mosquito Alert Tigapics image-level labels",
        "output_format": "ImageFolder with manifest",
        "image_storage": "copy" if copy_images else "symlink",
        "total_items": len(load_file_items(source_dir)),
        "usable_images": len(samples),
        "skipped_count": len(skipped),
        "skipped_by_reason": dict(Counter(item["reason"] for item in skipped)),
        "class_counts": dict(sorted(class_counts.items())),
        "confidence_counts": dict(sorted(confidence_counts.items())),
        "splits": {split: dict(sorted(counter.items())) for split, counter in split_counts.items()},
        "note": "This dataset has image-level species labels only; it does not contain detection bounding boxes.",
        "skipped": skipped[:200],
    }
    return samples, summary


def write_manifest(samples: list[PreparedSample], output_dir: Path) -> None:
    manifest_path = output_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "split": sample.split,
                    "class_name": sample.class_name,
                    "confidence": sample.confidence,
                    "report_id": sample.report_id,
                    "date": sample.date,
                    "location": sample.location,
                    "source_path": sample.source_path.relative_to(REPO_ROOT).as_posix(),
                    "output_path": sample.output_path.relative_to(REPO_ROOT).as_posix(),
                    "width": sample.width,
                    "height": sample.height,
                    "size": sample.size,
                }
            )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    reset_output_dir(args.output_dir, args.clean)
    samples, summary = prepare_samples(args.source_dir, args.output_dir, args.val_ratio, args.copy_images)
    write_manifest(samples, args.output_dir)
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.output_dir / "classes.json", sorted(summary["class_counts"]))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
