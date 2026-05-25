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

import csv
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
def train_pipeline(records: list[dict], size: tuple[int, int]) -> Pipeline:
    """Fit StandardScaler + PCA + LogisticRegression on pixel features."""
    trainable = [r for r in records if r["binary_label"] >= 0]

    X = np.vstack(
        [load_pixel_features(REPO_ROOT / r["relative_path"], size) for r in trainable]
    ).astype(np.float32)
    y = np.array([r["binary_label"] for r in trainable], dtype=np.int32)

    n_samples, n_features = X.shape
    n_pca = min(32, n_features, n_samples - 1)

    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("pca", PCA(n_components=n_pca, random_state=42)),
            ("lr", LogisticRegression(
                class_weight={0: 1.0, 1: 1.5},
                max_iter=4000,
                random_state=42,
                solver="liblinear",
            )),
        ]
    )
    pipe.fit(X, y)
    return pipe


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
    print("Loading manifest ...")
    records = load_records(MANIFEST_PATH)
    trainable = [r for r in records if r["binary_label"] >= 0]
    pos = sum(1 for r in trainable if r["binary_label"] == 1)
    neg = len(trainable) - pos
    print(f"  {len(trainable)} trainable samples  (pos={pos}, neg={neg})")

    print(f"\nTraining on {IMAGE_SIZE}x{IMAGE_SIZE} grayscale pixel features ...")
    pipe = train_pipeline(records, (IMAGE_SIZE, IMAGE_SIZE))

    print("\nExporting CoreML model ...")
    export_coreml(pipe, (IMAGE_SIZE, IMAGE_SIZE), OUTPUT_PATH)

    print(
        "\nDone.  The mlmodel is in the Mosquito-finder target folder and will be"
        "\nauto-compiled by Xcode.  Activate the model-loading code in"
        "\nStage2Classifier.swift to complete the wiring."
    )


if __name__ == "__main__":
    main()
