#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = REPO_ROOT / "data" / "external" / "kaggle_low_light_mosquito" / "dataset"
DEFAULT_REPORT_PATH = REPO_ROOT / "training" / "KAGGLE_LOW_LIGHT_VALIDATION.md"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Kaggle low-light mosquito YOLO labels.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser


def collect_files(root: Path, extensions: set[str] | None = None) -> list[Path]:
    if not root.exists():
        return []
    files = [path for path in root.rglob("*") if path.is_file()]
    if extensions is None:
        return sorted(files)
    return sorted(path for path in files if path.suffix.lower() in extensions)


def relative_basename(path: Path) -> str:
    return path.stem


def validate_label_file(path: Path) -> list[str]:
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
            values = [float(value) for value in parts[1:]]
        except ValueError:
            errors.append(f"{path}:{line_number}: non-numeric YOLO field")
            continue
        if class_id < 0:
            errors.append(f"{path}:{line_number}: negative class id {class_id}")
        if any(value < 0.0 or value > 1.0 for value in values):
            errors.append(f"{path}:{line_number}: normalized box value outside [0, 1]")
        if values[2] <= 0.0 or values[3] <= 0.0:
            errors.append(f"{path}:{line_number}: non-positive box width or height")
    return errors


def format_paths(paths: list[Path], root: Path, limit: int = 20) -> list[str]:
    formatted = [f"- `{path.relative_to(root)}`" for path in paths[:limit]]
    if len(paths) > limit:
        formatted.append(f"- ... {len(paths) - limit} more")
    return formatted


def main() -> None:
    args = build_parser().parse_args()
    dataset_dir = args.dataset_dir
    train_dir = dataset_dir / "train_dark"
    test_dir = dataset_dir / "test_dark"

    train_images = collect_files(train_dir / "images", IMAGE_EXTENSIONS)
    train_labels = collect_files(train_dir / "labels", {".txt"})
    test_images = collect_files(test_dir / "images", IMAGE_EXTENSIONS)
    test_labels = collect_files(test_dir / "labels", {".txt"})

    image_by_name: dict[str, list[Path]] = {}
    for image_path in train_images:
        image_by_name.setdefault(relative_basename(image_path), []).append(image_path)

    label_by_name: dict[str, list[Path]] = {}
    for label_path in train_labels:
        label_by_name.setdefault(relative_basename(label_path), []).append(label_path)

    image_names = set(image_by_name)
    label_names = set(label_by_name)
    missing_label_names = sorted(image_names - label_names)
    orphan_label_names = sorted(label_names - image_names)
    duplicate_image_names = sorted(name for name, paths in image_by_name.items() if len(paths) > 1)
    duplicate_label_names = sorted(name for name, paths in label_by_name.items() if len(paths) > 1)

    label_errors: list[str] = []
    class_counter: Counter[int] = Counter()
    boxes = 0
    for label_path in train_labels:
        label_errors.extend(validate_label_file(label_path))
        for raw_line in label_path.read_text(encoding="utf-8").splitlines():
            parts = raw_line.strip().split()
            if len(parts) == 5:
                try:
                    class_counter[int(parts[0])] += 1
                    boxes += 1
                except ValueError:
                    pass

    missing_label_paths = [path for name in missing_label_names for path in image_by_name[name]]
    orphan_label_paths = [path for name in orphan_label_names for path in label_by_name[name]]
    duplicate_image_paths = [path for name in duplicate_image_names for path in image_by_name[name]]
    duplicate_label_paths = [path for name in duplicate_label_names for path in label_by_name[name]]

    report: list[str] = [
        "# Kaggle Low Light Validation",
        "",
        "Updated: 2026-06-05",
        "",
        "## Summary",
        "",
        f"- Dataset directory: `{dataset_dir}`",
        f"- Train images: {len(train_images)}",
        f"- Train labels: {len(train_labels)}",
        f"- Test images: {len(test_images)}",
        f"- Test labels: {len(test_labels)}",
        f"- Total train boxes: {boxes}",
        f"- Class IDs: {dict(sorted(class_counter.items()))}",
        "",
        "## Findings",
        "",
        f"- Missing train labels: {len(missing_label_paths)} image files across {len(missing_label_names)} basename(s).",
        f"- Orphan train labels: {len(orphan_label_paths)} file(s).",
        f"- Duplicate train image basenames: {len(duplicate_image_names)}.",
        f"- Duplicate train label basenames: {len(duplicate_label_names)}.",
        f"- YOLO label format errors: {len(label_errors)}.",
        f"- Test split has labels: {'yes' if test_labels else 'no'}.",
        "",
    ]

    if missing_label_paths:
        report.extend(["## Missing Train Labels", ""])
        report.extend(format_paths(missing_label_paths, dataset_dir))
        report.append("")
    if orphan_label_paths:
        report.extend(["## Orphan Train Labels", ""])
        report.extend(format_paths(orphan_label_paths, dataset_dir))
        report.append("")
    if duplicate_image_paths:
        report.extend(["## Duplicate Train Image Basenames", ""])
        report.extend(format_paths(duplicate_image_paths, dataset_dir))
        report.append("")
    if duplicate_label_paths:
        report.extend(["## Duplicate Train Label Basenames", ""])
        report.extend(format_paths(duplicate_label_paths, dataset_dir))
        report.append("")
    if label_errors:
        report.extend(["## Label Format Errors", ""])
        report.extend(f"- `{error}`" for error in label_errors[:50])
        if len(label_errors) > 50:
            report.append(f"- ... {len(label_errors) - 50} more")
        report.append("")

    args.report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"wrote {args.report_path}")


if __name__ == "__main__":
    main()
