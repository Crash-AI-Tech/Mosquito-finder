#!/usr/bin/env python3
"""
Train a pixel-only sklearn classifier and export to CoreML Image Classifier.

The exported .mlmodel takes a 64×64 GRAYSCALE image and outputs:
  - classLabel         (String)                  : "mosquito" or "not_mosquito"
  - classLabelProbs    (Dictionary<String,Double>): confidence per class

Compatible with VNCoreMLRequest → VNClassificationObservation in iOS/Vision.

Architecture (forward pass):
  GRAYSCALE image (64×64) → flatten (4096,) → normalize+scale (per-pixel)
  → PCA projection (n_pca dims) → logistic-regression head (2 logits)
  → softmax → classLabelProbs

Implementation note:
  The model spec is built via coremltools protobuf API directly, so it is
  independent of the high-level NeuralNetworkBuilder API changes across
  coremltools versions.

Usage:
    .venv/bin/python training/export_coreml.py

Output:
    Mosquito-finder/Mosquito-finder/MosquitoClassifier.mlmodel
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT     = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "artifacts" / "baseline_synthetic" / "manifest.csv"
OUTPUT_PATH   = REPO_ROOT / "Mosquito-finder" / "MosquitoClassifier.mlmodel"

IMAGE_SIZE   = 64              # px per side — matches CoreML input spec
CLASS_LABELS = ["not_mosquito", "mosquito"]   # index 0 = negative, 1 = positive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and export the Stage-2 mosquito CoreML classifier."
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--metrics-output", type=Path, default=None)
    parser.add_argument("--image-size", type=int, default=IMAGE_SIZE)
    parser.add_argument(
        "--train-splits",
        nargs="+",
        default=None,
        help="Manifest split values used for fitting. Defaults to all trainable rows.",
    )
    parser.add_argument(
        "--eval-splits",
        nargs="+",
        default=None,
        help="Manifest split values used for held-out metrics.",
    )
    parser.add_argument(
        "--negative-weight",
        type=float,
        default=1.6,
        help="Higher values reduce false positives by emphasizing hard negatives.",
    )
    parser.add_argument("--positive-weight", type=float, default=1.0)
    return parser


# ---------------------------------------------------------------------------
# Feature extraction (pixel-only — identical to CoreML forward pass)
# ---------------------------------------------------------------------------
def load_pixel_features(image_path: Path, size: tuple[int, int]) -> np.ndarray:
    """Return flattened grayscale image as float32 in [0, 1]."""
    with Image.open(image_path) as img:
        gray = img.convert("L").resize(size, Image.Resampling.BILINEAR)
    return np.asarray(gray, dtype=np.float32).flatten() / 255.0


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def load_records(manifest_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["binary_label"] = int(row["binary_label"])
            records.append(row)
    return records


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train_pipeline(
    records: list[dict],
    size: tuple[int, int],
    negative_weight: float,
    positive_weight: float,
    train_splits: list[str] | None = None,
) -> Pipeline:
    """Fit StandardScaler + PCA + LogisticRegression on pixel features."""
    trainable = [
        r for r in records
        if r["binary_label"] >= 0
        and (train_splits is None or r.get("split") in train_splits)
    ]

    X = np.vstack(
        [load_pixel_features(REPO_ROOT / r["relative_path"], size) for r in trainable]
    ).astype(np.float32)
    y = np.array([r["binary_label"] for r in trainable], dtype=np.int32)

    n_samples, n_features = X.shape
    n_pca = min(32, n_features, n_samples - 1)

    scaler = StandardScaler().fit(X)
    # Detector-derived crops contain many nearly constant border pixels.
    # Flooring the scale keeps the CoreML scale layer finite and avoids
    # over-amplifying meaningless sub-pixel variance.
    scaler.scale_ = np.maximum(scaler.scale_, 1e-3)
    scaled = scaler.transform(X)

    pca = PCA(n_components=n_pca, random_state=42, svd_solver="randomized")
    projected = pca.fit_transform(scaled)

    lr = LogisticRegression(
        class_weight={0: negative_weight, 1: positive_weight},
        max_iter=4000,
        random_state=42,
        solver="liblinear",
    )
    lr.fit(projected, y)

    return Pipeline([("scaler", scaler), ("pca", pca), ("lr", lr)])


def evaluate_pipeline(
    pipe: Pipeline,
    records: list[dict[str, Any]],
    size: tuple[int, int],
    eval_splits: list[str] | None,
    thresholds: list[float],
) -> dict[str, Any] | None:
    eval_records = [
        r for r in records
        if r["binary_label"] >= 0
        and (eval_splits is None or r.get("split") in eval_splits)
    ]
    if not eval_records:
        return None

    X = np.vstack(
        [load_pixel_features(REPO_ROOT / r["relative_path"], size) for r in eval_records]
    ).astype(np.float32)
    y = np.array([r["binary_label"] for r in eval_records], dtype=np.int32)
    probabilities = pipe.predict_proba(X)[:, 1]

    metrics = []
    for threshold in thresholds:
        predictions = probabilities >= threshold
        tp = int(((predictions == 1) & (y == 1)).sum())
        fp = int(((predictions == 1) & (y == 0)).sum())
        tn = int(((predictions == 0) & (y == 0)).sum())
        fn = int(((predictions == 0) & (y == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        accuracy = (tp + tn) / max(1, len(y))
        f1 = 2 * precision * recall / max(1e-9, precision + recall)
        metrics.append(
            {
                "threshold": threshold,
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "true_positive": tp,
                "false_positive": fp,
                "true_negative": tn,
                "false_negative": fn,
            }
        )

    return {
        "samples": len(eval_records),
        "positives": int(y.sum()),
        "negatives": int((y == 0).sum()),
        "splits": eval_splits,
        "positive_quantiles": np.quantile(
            probabilities[y == 1],
            [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1],
        ).round(6).tolist() if int(y.sum()) else [],
        "negative_quantiles": np.quantile(
            probabilities[y == 0],
            [0, 0.5, 0.75, 0.9, 0.95, 0.99, 1],
        ).round(6).tolist() if int((y == 0).sum()) else [],
        "metrics": metrics,
    }


# ---------------------------------------------------------------------------
# CoreML export  (builds spec via protobuf API — works with any coremltools)
# ---------------------------------------------------------------------------
def export_coreml(
    pipe: Pipeline,
    size: tuple[int, int],
    output_path: Path,
) -> None:
    import coremltools as ct
    from coremltools.proto import Model_pb2, FeatureTypes_pb2

    scaler = pipe.named_steps["scaler"]
    pca    = pipe.named_steps["pca"]
    lr     = pipe.named_steps["lr"]

    H, W  = size
    N     = H * W            # 4096
    n_pca = pca.n_components_

    # ── weight matrices ───────────────────────────────────────────────────
    #
    # After flatten the internal CoreML tensor is (N, 1, 1).
    #
    # Layer "normalize" (ScaleLayerParams):
    #   maps raw pixel x ∈ [0,255] → scaler-normalised value
    #   x_sc = x / (255 * scale_) - (mean_ / scale_)
    scale_w = (1.0 / (255.0 * scaler.scale_)).astype(np.float32)   # (N,)
    scale_b = (-scaler.mean_ / scaler.scale_).astype(np.float32)    # (N,)

    # Layer "pca" (InnerProductLayerParams):
    #   x_pca = (x_sc - pca.mean_) @ components_.T
    #         = x_sc @ components_.T + (-pca.mean_ @ components_.T)
    W_pca = pca.components_.astype(np.float32)                       # (n_pca, N)
    b_pca = (-pca.mean_ @ pca.components_.T).astype(np.float32)     # (n_pca,)

    # Layer "lr" (InnerProductLayerParams, 2 outputs for softmax):
    #   logit_pos = coef_[0] @ x_pca + intercept_[0]
    #   logit_neg = -logit_pos  (binary symmetric split)
    W_lr_1 = lr.coef_.astype(np.float32)                             # (1, n_pca)
    b_lr_1 = lr.intercept_.astype(np.float32)                        # (1,)
    W_lr   = np.vstack([-W_lr_1, W_lr_1])                           # (2, n_pca)
    b_lr   = np.array([-b_lr_1[0], b_lr_1[0]], dtype=np.float32)   # (2,)

    for name, values in {
        "scale_w": scale_w,
        "scale_b": scale_b,
        "W_pca": W_pca,
        "b_pca": b_pca,
        "W_lr": W_lr,
        "b_lr": b_lr,
    }.items():
        if not np.isfinite(values).all():
            raise ValueError(f"Non-finite CoreML parameter generated: {name}")

    # ── build spec ────────────────────────────────────────────────────────
    spec = Model_pb2.Model()
    spec.specificationVersion = 4   # CoreML 4 / iOS 14+

    # Input: GRAYSCALE image H×W
    img_in = spec.description.input.add()
    img_in.name = "image"
    img_in.type.imageType.width      = W
    img_in.type.imageType.height     = H
    img_in.type.imageType.colorSpace = FeatureTypes_pb2.ImageFeatureType.GRAYSCALE

    # Output 1: classLabel (String)
    lbl_out = spec.description.output.add()
    lbl_out.name = "classLabel"
    lbl_out.type.stringType.SetInParent()

    # Output 2: classLabelProbs (Dictionary<String, Double>)
    prob_out = spec.description.output.add()
    prob_out.name = "classLabelProbs"
    prob_out.type.dictionaryType.stringKeyType.SetInParent()

    spec.description.predictedFeatureName        = "classLabel"
    spec.description.predictedProbabilitiesName  = "classLabelProbs"

    # Model type: NeuralNetworkClassifier
    nn = spec.neuralNetworkClassifier
    nn.stringClassLabels.vector.extend(CLASS_LABELS)
    # labelProbabilityLayerName intentionally left empty →
    # CoreML uses the last layer's output as the probability source

    # ── layers ────────────────────────────────────────────────────────────

    # Layer 1 – Flatten: (1, H, W) → (N, 1, 1)
    flat = nn.layers.add()
    flat.name = "flatten"
    flat.input.append("image")
    flat.output.append("flat")
    flat.flatten.mode = 0   # CHANNEL_FIRST

    # Layer 2 – Scale+bias: normalize raw pixels then apply StandardScaler
    sc = nn.layers.add()
    sc.name = "normalize"
    sc.input.append("flat")
    sc.output.append("scaled")
    sc.scale.scale.floatValue.extend(scale_w.tolist())
    sc.scale.shapeScale.extend([N, 1, 1])
    sc.scale.hasBias = True
    sc.scale.bias.floatValue.extend(scale_b.tolist())
    sc.scale.shapeBias.extend([N, 1, 1])

    # Layer 3 – Inner product: PCA projection  (N,) → (n_pca,)
    ip1 = nn.layers.add()
    ip1.name = "pca"
    ip1.input.append("scaled")
    ip1.output.append("pca_out")
    ip1.innerProduct.inputChannels  = N
    ip1.innerProduct.outputChannels = n_pca
    ip1.innerProduct.hasBias        = True
    ip1.innerProduct.weights.floatValue.extend(W_pca.flatten().tolist())
    ip1.innerProduct.bias.floatValue.extend(b_pca.tolist())

    # Layer 4 – Inner product: LR head  (n_pca,) → (2,)
    ip2 = nn.layers.add()
    ip2.name = "lr"
    ip2.input.append("pca_out")
    ip2.output.append("logits")
    ip2.innerProduct.inputChannels  = n_pca
    ip2.innerProduct.outputChannels = 2
    ip2.innerProduct.hasBias        = True
    ip2.innerProduct.weights.floatValue.extend(W_lr.flatten().tolist())
    ip2.innerProduct.bias.floatValue.extend(b_lr.tolist())

    # Layer 5 – Softmax: (2,) → class probabilities
    sm = nn.layers.add()
    sm.name = "softmax"
    sm.input.append("logits")
    sm.output.append("classLabelProbs")
    sm.softmax.SetInParent()

    # ── metadata ──────────────────────────────────────────────────────────
    spec.description.metadata.shortDescription = (
        "Mosquito Finder Stage-2 binary classifier. "
        "Input: GRAYSCALE 64x64. "
        "Output: classLabel in {mosquito, not_mosquito}."
    )
    spec.description.metadata.author = "Mosquito Finder ML Pipeline"

    # ── save (write raw protobuf bytes; bypasses MLModel wrapper which may
    #         transform the spec when native C extensions are unavailable) ──
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(output_path), "wb") as fh:
        fh.write(spec.SerializeToString())

    print(f"Saved: {output_path}")
    print(f"  Input  : GRAYSCALE {W}x{H}  (Vision handles crop+resize from ROI)")
    print(f"  Labels : {CLASS_LABELS}")
    print(f"  Arch   : Scaler({N}) -> PCA({n_pca}) -> LogReg(2) -> Softmax")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    args = build_parser().parse_args()
    image_size = (args.image_size, args.image_size)

    print("Loading manifest ...")
    records = load_records(args.manifest)
    trainable = [r for r in records if r["binary_label"] >= 0]
    pos = sum(1 for r in trainable if r["binary_label"] == 1)
    neg = len(trainable) - pos
    print(f"  {len(trainable)} trainable samples  (pos={pos}, neg={neg})")

    print(f"\nTraining on {args.image_size}x{args.image_size} grayscale pixel features ...")
    print(f"  class weights: negative={args.negative_weight}, positive={args.positive_weight}")
    if args.train_splits:
        print(f"  train splits: {', '.join(args.train_splits)}")
    pipe = train_pipeline(
        records,
        image_size,
        negative_weight=args.negative_weight,
        positive_weight=args.positive_weight,
        train_splits=args.train_splits,
    )

    metrics = evaluate_pipeline(
        pipe,
        records,
        image_size,
        eval_splits=args.eval_splits,
        thresholds=[0.50, 0.70, 0.80, 0.90, 0.95],
    )
    if metrics is not None:
        print("\nHeld-out metrics:")
        for metric in metrics["metrics"]:
            print(
                f"  threshold={metric['threshold']:.2f} "
                f"accuracy={metric['accuracy']:.3f} "
                f"precision={metric['precision']:.3f} "
                f"recall={metric['recall']:.3f} "
                f"f1={metric['f1']:.3f}"
            )
        if args.metrics_output:
            args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
            args.metrics_output.write_text(
                json.dumps(metrics, indent=2) + "\n",
                encoding="utf-8",
            )

    print("\nExporting CoreML model ...")
    export_coreml(pipe, image_size, args.output)

    print(
        "\nDone.  The mlmodel is in the Mosquito-finder target folder and will be"
        "\nauto-compiled by Xcode.  Activate the model-loading code in"
        "\nStage2Classifier.swift to complete the wiring."
    )


if __name__ == "__main__":
    main()
