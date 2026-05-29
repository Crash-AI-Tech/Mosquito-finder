#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

from baseline_common import (
    DEFAULT_OUTPUT_DIR,
    build_feature_matrix,
    dump_json,
    load_manifest,
    make_baseline_pipeline,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a synthetic Stage 2 baseline classifier.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "manifest.csv",
        help="Path to the manifest created by prepare_dataset_manifest.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where model and metrics will be written.",
    )
    parser.add_argument(
        "--image-size",
        type=int,
        default=64,
        help="Square resize dimension used for feature extraction.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Probability threshold for mosquito prediction.",
    )
    return parser


def build_sample_weights(records: list[dict[str, object]]) -> np.ndarray:
    weights = np.ones(len(records), dtype=np.float32)
    for index, record in enumerate(records):
        label = record["label"]
        if label == "hardnegative":
            weights[index] = 1.5
        elif label == "mosquito":
            weights[index] = 1.2
    return weights


def summarize_metrics(metrics: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for key in ("accuracy", "precision", "recall", "f1"):
        values = np.array([metric[key] for metric in metrics], dtype=np.float32)
        summary[key] = {
            "mean": float(values.mean()),
            "std": float(values.std()),
            "min": float(values.min()),
            "max": float(values.max()),
        }
    return summary


def main() -> None:
    args = build_parser().parse_args()
    records = [record for record in load_manifest(args.manifest) if int(record["binary_label"]) >= 0]
    if not records:
        raise ValueError("Manifest does not contain any trainable records.")

    image_size = (args.image_size, args.image_size)
    features = build_feature_matrix(records, image_size=image_size)
    labels = np.array([int(record["binary_label"]) for record in records], dtype=np.int32)
    folds = np.array([int(record["fold"]) for record in records], dtype=np.int32)
    sample_weights = build_sample_weights(records)

    fold_metrics: list[dict[str, float]] = []
    prediction_rows: list[dict[str, object]] = []

    for fold in sorted({int(fold) for fold in folds if fold >= 0}):
        test_mask = folds == fold
        train_mask = folds != fold
        if train_mask.sum() == 0 or test_mask.sum() == 0:
            continue

        pipeline = make_baseline_pipeline(
            feature_count=features.shape[1],
            sample_count=int(train_mask.sum()),
            random_state=42 + fold,
        )
        pipeline.fit(
            features[train_mask],
            labels[train_mask],
            classifier__sample_weight=sample_weights[train_mask],
        )

        probabilities = pipeline.predict_proba(features[test_mask])[:, 1]
        predictions = (probabilities >= args.threshold).astype(np.int32)
        truths = labels[test_mask]
        confusion = confusion_matrix(truths, predictions, labels=[0, 1])

        metrics = {
            "fold": float(fold),
            "accuracy": float(accuracy_score(truths, predictions)),
            "precision": float(precision_score(truths, predictions, zero_division=0)),
            "recall": float(recall_score(truths, predictions, zero_division=0)),
            "f1": float(f1_score(truths, predictions, zero_division=0)),
            "test_samples": float(int(test_mask.sum())),
            "tn": float(confusion[0, 0]),
            "fp": float(confusion[0, 1]),
            "fn": float(confusion[1, 0]),
            "tp": float(confusion[1, 1]),
        }
        fold_metrics.append(metrics)

        for record, probability, prediction, truth in zip(
            np.array(records, dtype=object)[test_mask],
            probabilities,
            predictions,
            truths,
        ):
            prediction_rows.append(
                {
                    "file_name": record["file_name"],
                    "base_id": record["base_id"],
                    "scene": record["scene"],
                    "variant": record["variant"],
                    "variant_tag": record["variant_tag"],
                    "label": record["label"],
                    "fold": fold,
                    "truth": int(truth),
                    "mosquito_score": float(probability),
                    "prediction": int(prediction),
                    "correct": int(prediction == truth),
                }
            )

    if not fold_metrics:
        raise ValueError("No folds were trainable. Check manifest fold assignments.")

    final_pipeline = make_baseline_pipeline(
        feature_count=features.shape[1],
        sample_count=len(records),
        random_state=42,
    )
    final_pipeline.fit(features, labels, classifier__sample_weight=sample_weights)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "stage2_baseline_synthetic.joblib"
    predictions_path = args.output_dir / "cv_predictions.csv"
    metrics_path = args.output_dir / "cv_metrics.json"

    joblib.dump(
        {
            "pipeline": final_pipeline,
            "threshold": args.threshold,
            "image_size": image_size,
            "feature_version": "gray64-edge-v1",
            "positive_label": "mosquito",
            "negative_labels": ["notmosquito", "hardnegative"],
        },
        model_path,
    )

    with predictions_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "file_name",
            "base_id",
            "scene",
            "variant",
            "variant_tag",
            "label",
            "fold",
            "truth",
            "mosquito_score",
            "prediction",
            "correct",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in prediction_rows:
            writer.writerow(row)

    metrics_payload = {
        "threshold": args.threshold,
        "image_size": list(image_size),
        "fold_metrics": fold_metrics,
        "aggregate_metrics": summarize_metrics(fold_metrics),
        "trainable_image_count": len(records),
        "positive_image_count": int(labels.sum()),
        "negative_image_count": int((labels == 0).sum()),
    }
    dump_json(metrics_path, metrics_payload)

    aggregate = metrics_payload["aggregate_metrics"]
    print(f"Model written to: {model_path}")
    print(f"Predictions written to: {predictions_path}")
    print(f"Metrics written to: {metrics_path}")
    print(
        "CV summary: "
        f"acc={aggregate['accuracy']['mean']:.3f}, "
        f"precision={aggregate['precision']['mean']:.3f}, "
        f"recall={aggregate['recall']['mean']:.3f}, "
        f"f1={aggregate['f1']['mean']:.3f}"
    )


if __name__ == "__main__":
    main()
