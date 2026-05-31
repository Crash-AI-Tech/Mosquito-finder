#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import coremltools as ct
import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = REPO_ROOT / "data" / "detector" / "generated_dfine"
DEFAULT_DFINE_MODEL = REPO_ROOT / "Mosquito-finder" / "DfineMosquitoDetector.mlpackage"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate CoreML detector confidence on COCO splits.")
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_DFINE_MODEL)
    parser.add_argument("--splits", nargs="+", default=["val2017", "reality2017"])
    parser.add_argument("--thresholds", nargs="+", type=float, default=[0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9])
    parser.add_argument("--image-size", type=int, default=416)
    return parser


def annotated_image_ids(annotation_path: Path) -> set[int]:
    data = json.loads(annotation_path.read_text())
    return {
        annotation["image_id"]
        for annotation in data.get("annotations", [])
        if annotation.get("bbox", [0, 0, 0, 0])[2] > 0
    }


def detector_score(outputs: dict[str, object]) -> float:
    score_output = next(value for key, value in outputs.items() if "score" in key.lower())
    return float(np.asarray(score_output).max())


def evaluate_split(
    model: ct.models.MLModel,
    dataset_dir: Path,
    split: str,
    image_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    annotation_path = dataset_dir / "annotations" / f"instances_{split}.json"
    data = json.loads(annotation_path.read_text())
    positive_ids = annotated_image_ids(annotation_path)

    scores: list[float] = []
    labels: list[bool] = []
    timings: list[float] = []

    for image in data["images"]:
        image_path = dataset_dir / split / image["file_name"]
        pil_image = Image.open(image_path).convert("RGB").resize((image_size, image_size))
        start = time.perf_counter()
        outputs = model.predict({"images": pil_image})
        timings.append(time.perf_counter() - start)
        scores.append(detector_score(outputs))
        labels.append(image["id"] in positive_ids)

    return np.asarray(scores), np.asarray(labels, dtype=bool), np.asarray(timings)


def print_metrics(scores: np.ndarray, labels: np.ndarray, timings: np.ndarray, thresholds: list[float]) -> None:
    print(
        f"images={len(scores)} positives={int(labels.sum())} negatives={int((~labels).sum())} "
        f"mean_ms={timings.mean() * 1000:.2f} p95_ms={np.quantile(timings, 0.95) * 1000:.2f}"
    )
    print("positive_quantiles=", np.quantile(scores[labels], [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]).round(4).tolist())
    print("negative_quantiles=", np.quantile(scores[~labels], [0, 0.5, 0.75, 0.9, 0.95, 0.99, 1]).round(4).tolist())

    for threshold in thresholds:
        predictions = scores >= threshold
        tp = int((predictions & labels).sum())
        fp = int((predictions & ~labels).sum())
        fn = int((~predictions & labels).sum())
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        print(
            f"threshold={threshold:.2f} tp={tp} fp={fp} fn={fn} "
            f"precision={precision:.3f} recall={recall:.3f}"
        )


def main() -> None:
    args = build_parser().parse_args()
    model = ct.models.MLModel(str(args.model))
    for split in args.splits:
        print(f"\n[{split}]")
        scores, labels, timings = evaluate_split(model, args.dataset_dir, split, args.image_size)
        print_metrics(scores, labels, timings, args.thresholds)


if __name__ == "__main__":
    main()
