#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib

from baseline_common import load_feature_vector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Predict mosquito probability for a single ROI image.")
    parser.add_argument("image", type=Path, help="Path to a .jpg image.")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("artifacts/baseline_synthetic/stage2_baseline_synthetic.joblib"),
        help="Path to the saved joblib baseline bundle.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bundle = joblib.load(args.model)
    feature_vector = load_feature_vector(args.image.resolve(), tuple(bundle["image_size"]))
    mosquito_score = float(bundle["pipeline"].predict_proba([feature_vector])[0, 1])
    threshold = float(bundle["threshold"])

    result = {
        "image": args.image.as_posix(),
        "mosquito_score": mosquito_score,
        "threshold": threshold,
        "predicted_label": "mosquito" if mosquito_score >= threshold else "not_mosquito",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
