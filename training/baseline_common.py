from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = REPO_ROOT / "data" / "synthetic"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "baseline_synthetic"

VALID_LABELS = {"mosquito", "notmosquito", "hardnegative", "uncertain"}
LABEL_TO_BINARY = {
    "mosquito": 1,
    "notmosquito": 0,
    "hardnegative": 0,
    "uncertain": -1,
}

FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{8})_"
    r"(?P<source>[^_]+)_"
    r"(?P<scene>[^_]+)_"
    r"(?P<zoom>[^_]+)_"
    r"(?P<torch>[^_]+)_"
    r"(?P<label>mosquito|notmosquito|hardnegative|uncertain)_"
    r"(?P<index>\d+)"
    r"(?:_(?P<variant>var[^_]+)_(?P<variant_tag>.+))?"
)

MANIFEST_FIELDS = [
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
]


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_image_record(image_path: Path, dataset_dir: Path) -> dict[str, Any]:
    match = FILENAME_PATTERN.fullmatch(image_path.stem)
    if match is None:
        raise ValueError(f"Unsupported filename format: {image_path.name}")

    data = match.groupdict(default="")
    label = data["label"]
    if label not in VALID_LABELS:
        raise ValueError(f"Unsupported label in filename: {image_path.name}")

    base_id = "_".join(
        [
            data["date"],
            data["source"],
            data["scene"],
            data["zoom"],
            data["torch"],
            data["label"],
            data["index"],
        ]
    )

    with Image.open(image_path) as image:
        width, height = image.size

    return {
        "file_name": image_path.name,
        "relative_path": image_path.relative_to(REPO_ROOT).as_posix(),
        "date": data["date"],
        "source": data["source"],
        "scene": data["scene"],
        "zoom": data["zoom"],
        "torch": data["torch"],
        "label": label,
        "binary_label": LABEL_TO_BINARY[label],
        "index": data["index"],
        "base_id": base_id,
        "variant": data["variant"] or "base",
        "variant_tag": data["variant_tag"] or "base",
        "image_width": width,
        "image_height": height,
        "fold": -1,
        "split": "exclude",
    }


def scan_dataset(dataset_dir: Path | None = None) -> list[dict[str, Any]]:
    resolved_dir = (dataset_dir or DEFAULT_DATASET_DIR).resolve()
    if not resolved_dir.exists():
        raise FileNotFoundError(f"Dataset directory does not exist: {resolved_dir}")

    records = [parse_image_record(path, resolved_dir) for path in sorted(resolved_dir.glob("*.jpg"))]
    if not records:
        raise FileNotFoundError(f"No .jpg files found in dataset directory: {resolved_dir}")
    return records


def assign_group_folds(records: list[dict[str, Any]], fold_count: int = 3) -> list[dict[str, Any]]:
    base_to_label: dict[str, str] = {}
    groups_by_label: dict[str, list[str]] = defaultdict(list)

    for record in records:
        base_id = record["base_id"]
        label = record["label"]
        existing = base_to_label.get(base_id)
        if existing is not None and existing != label:
            raise ValueError(f"Base group contains mixed labels: {base_id}")
        base_to_label[base_id] = label

    for base_id, label in sorted(base_to_label.items()):
        if label == "uncertain":
            continue
        groups_by_label[label].append(base_id)

    fold_map: dict[str, int] = {}
    for label in ("mosquito", "hardnegative", "notmosquito"):
        for index, base_id in enumerate(sorted(groups_by_label[label])):
            fold_map[base_id] = index % fold_count

    assigned_records: list[dict[str, Any]] = []
    for record in records:
        updated = dict(record)
        fold = fold_map.get(updated["base_id"], -1)
        updated["fold"] = fold
        updated["split"] = f"fold_{fold}" if fold >= 0 else "exclude"
        assigned_records.append(updated)

    return assigned_records


def build_dataset_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    image_label_counts = Counter(record["label"] for record in records)
    base_label_counts = Counter()
    fold_label_counts: dict[str, Counter[str]] = defaultdict(Counter)
    image_sizes = Counter((record["image_width"], record["image_height"]) for record in records)

    seen_base_ids = set()
    for record in records:
        base_id = record["base_id"]
        if base_id not in seen_base_ids:
            base_label_counts[record["label"]] += 1
            seen_base_ids.add(base_id)
        fold_label_counts[str(record["fold"])][record["label"]] += 1

    return {
        "total_images": len(records),
        "total_base_groups": len(seen_base_ids),
        "image_label_counts": dict(sorted(image_label_counts.items())),
        "base_label_counts": dict(sorted(base_label_counts.items())),
        "fold_label_counts": {
            fold: dict(sorted(counts.items()))
            for fold, counts in sorted(fold_label_counts.items(), key=lambda item: item[0])
        },
        "image_sizes": {
            f"{width}x{height}": count for (width, height), count in sorted(image_sizes.items())
        },
    }


def write_manifest(records: list[dict[str, Any]], manifest_path: Path) -> None:
    ensure_directory(manifest_path.parent)
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record[field] for field in MANIFEST_FIELDS})


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        records = []
        for row in reader:
            row["binary_label"] = int(row["binary_label"])
            row["image_width"] = int(row["image_width"])
            row["image_height"] = int(row["image_height"])
            row["fold"] = int(row["fold"])
            records.append(row)
    return records


def load_feature_vector(image_path: Path, image_size: tuple[int, int]) -> np.ndarray:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB").resize(image_size, Image.Resampling.BILINEAR)
        gray = rgb.convert("L")

    gray_array = np.asarray(gray, dtype=np.float32) / 255.0
    rgb_array = np.asarray(rgb, dtype=np.float32) / 255.0

    gradient_x = np.diff(gray_array, axis=1, prepend=gray_array[:, :1])
    gradient_y = np.diff(gray_array, axis=0, prepend=gray_array[:1, :])
    edge_magnitude = np.hypot(gradient_x, gradient_y)

    half_height = gray_array.shape[0] // 2
    half_width = gray_array.shape[1] // 2
    quadrants = [
        gray_array[:half_height, :half_width],
        gray_array[:half_height, half_width:],
        gray_array[half_height:, :half_width],
        gray_array[half_height:, half_width:],
    ]
    quadrant_means = np.array([quadrant.mean() for quadrant in quadrants], dtype=np.float32)
    quadrant_stds = np.array([quadrant.std() for quadrant in quadrants], dtype=np.float32)

    global_features = np.array(
        [
            gray_array.mean(),
            gray_array.std(),
            gray_array.min(),
            gray_array.max(),
            edge_magnitude.mean(),
            edge_magnitude.std(),
            *rgb_array.mean(axis=(0, 1)),
        ],
        dtype=np.float32,
    )

    return np.concatenate(
        [
            gray_array.flatten(),
            quadrant_means,
            quadrant_stds,
            global_features,
        ]
    )


def build_feature_matrix(
    records: list[dict[str, Any]], image_size: tuple[int, int]
) -> np.ndarray:
    features = [load_feature_vector(REPO_ROOT / record["relative_path"], image_size) for record in records]
    return np.vstack(features).astype(np.float32)


def make_baseline_pipeline(
    feature_count: int, sample_count: int, random_state: int = 42
) -> Pipeline:
    pca_components = min(32, feature_count, max(2, sample_count - 1))
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("pca", PCA(n_components=pca_components, random_state=random_state)),
            (
                "classifier",
                LogisticRegression(
                    class_weight={0: 1.0, 1: 1.5},
                    max_iter=4000,
                    random_state=random_state,
                    solver="liblinear",
                ),
            ),
        ]
    )
