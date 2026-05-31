#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
import torch.nn as nn


REPO_ROOT = Path(__file__).resolve().parent.parent
YOLOX_ROOT = REPO_ROOT / "external" / "YOLOX"
DEFAULT_EXP = REPO_ROOT / "training" / "yolox_mosquito_nano_reality.py"
DEFAULT_CHECKPOINT = REPO_ROOT / "YOLOX_outputs" / "yolox_mosquito_nano_reality" / "best_ckpt.pth"
DEFAULT_OUTPUT = REPO_ROOT / "Mosquito-finder" / "YoloxMosquitoDetector.mlmodel"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a trained YOLOX mosquito detector to CoreML.")
    parser.add_argument("--exp-file", type=Path, default=DEFAULT_EXP)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image-size", type=int, default=416)
    return parser


def load_yolox_model(exp_file: Path, checkpoint_path: Path) -> nn.Module:
    sys.path.insert(0, str(YOLOX_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "training"))

    from yolox.exp import get_exp  # type: ignore
    from yolox.models.network_blocks import SiLU  # type: ignore
    from yolox.utils import replace_module  # type: ignore

    exp = get_exp(str(exp_file), None)
    model = exp.get_model()

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    state = checkpoint["model"] if "model" in checkpoint else checkpoint
    model.load_state_dict(state)

    model = replace_module(model, nn.SiLU, SiLU)
    model.head.decode_in_inference = True
    model.eval()
    return model


def export_coreml(model: nn.Module, output_path: Path, image_size: int) -> None:
    import coremltools as ct

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample = torch.rand(1, 3, image_size, image_size)
    traced = torch.jit.trace(model, sample)

    coreml_model = ct.convert(
        traced,
        source="pytorch",
        inputs=[
            ct.ImageType(
                name="images",
                shape=(1, 3, image_size, image_size),
                scale=1.0 / 255.0,
            )
        ],
        outputs=[ct.TensorType(name="output")],
        minimum_deployment_target=ct.target.iOS14,
        convert_to="neuralnetwork",
    )
    coreml_model.short_description = (
        "YOLOX-Nano mosquito detector trained on the reality-split household hard-negative corpus."
    )
    coreml_model.author = "Mosquito Finder training pipeline"
    coreml_model.save(str(output_path))
    print(f"CoreML written to: {output_path}")


def main() -> None:
    args = build_parser().parse_args()
    model = load_yolox_model(args.exp_file, args.checkpoint)
    export_coreml(model, args.output, args.image_size)


if __name__ == "__main__":
    main()
