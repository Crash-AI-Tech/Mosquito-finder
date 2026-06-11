#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch
import torch.nn as nn


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
LOCAL_DFINE_ROOT = REPO_ROOT / "external" / "D-FINE"
SHARED_DFINE_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "D-FINE"
DFINE_ROOT = LOCAL_DFINE_ROOT if LOCAL_DFINE_ROOT.exists() else SHARED_DFINE_ROOT
DEFAULT_CONFIG = REPO_ROOT / "training" / "dfine_mosquito_n_long.yml"
DEFAULT_CHECKPOINT = REPO_ROOT / "artifacts" / "dfine_mosquito_n_long" / "best_stg2.pth"
DEFAULT_ONNX = REPO_ROOT / "artifacts" / "dfine_mosquito_n_long" / "DfineMosquitoDetectorScores.onnx"
DEFAULT_MLMODEL = REPO_ROOT / "Mosquito-finder" / "DfineMosquitoDetector.mlpackage"


class CoreMLFriendlyIntegral(nn.Module):
    """Equivalent to D-FINE Integral without F.linear, which CoreMLTools rejects here."""

    def __init__(self, reg_max: int) -> None:
        super().__init__()
        self.reg_max = reg_max

    def forward(self, x: torch.Tensor, project: torch.Tensor) -> torch.Tensor:
        shape = x.shape
        x = torch.softmax(x.reshape(-1, self.reg_max + 1), dim=1)
        weights = project.to(x.device).reshape(1, self.reg_max + 1)
        x = (x * weights).sum(dim=1, keepdim=True).reshape(-1, 4)
        return x.reshape(list(shape[:-1]) + [-1])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the trained D-FINE detector to an iOS-friendly CoreML model."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--onnx-output", type=Path, default=DEFAULT_ONNX)
    parser.add_argument("--mlmodel-output", type=Path, default=DEFAULT_MLMODEL)
    parser.add_argument("--image-size", type=int, default=416)
    parser.add_argument("--skip-onnx", action="store_true")
    parser.add_argument("--skip-coreml", action="store_true")
    parser.add_argument(
        "--raw-outputs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export raw scores and boxes instead of top-k postprocessed scores.",
    )
    return parser


def load_dfine_model(config_path: Path, checkpoint_path: Path, raw_outputs: bool) -> nn.Module:
    sys.path.insert(0, str(DFINE_ROOT))
    from src.core import YAMLConfig  # type: ignore

    cfg = YAMLConfig(str(config_path), resume=str(checkpoint_path))
    if "HGNetv2" in cfg.yaml_cfg:
        cfg.yaml_cfg["HGNetv2"]["pretrained"] = False

    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    state = checkpoint["ema"]["module"] if "ema" in checkpoint else checkpoint["model"]
    cfg.model.load_state_dict(state)

    class FixedSizeDfine(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = cfg.model.deploy()
            self.model.decoder.integral = CoreMLFriendlyIntegral(self.model.decoder.reg_max)
            self.postprocessor = cfg.postprocessor.deploy()

        def forward(self, images: torch.Tensor):
            outputs = self.model(images)
            if raw_outputs:
                return torch.sigmoid(outputs["pred_logits"]), outputs["pred_boxes"]

            batch_size = images.shape[0]
            target_sizes = torch.full(
                (batch_size, 2),
                fill_value=float(images.shape[-1]),
                dtype=torch.float32,
                device=images.device,
            )
            _, boxes, scores = self.postprocessor(outputs, target_sizes)
            return scores, boxes

    model = FixedSizeDfine()
    model.eval()
    return model


def export_onnx(model: nn.Module, output_path: Path, image_size: int) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sample = torch.rand(1, 3, image_size, image_size)
    torch.onnx.export(
        model,
        sample,
        str(output_path),
        input_names=["images"],
        output_names=["scores", "boxes"],
        dynamic_axes={"images": {0: "N"}, "scores": {0: "N"}, "boxes": {0: "N"}},
        opset_version=16,
        do_constant_folding=True,
    )
    print(f"ONNX written to: {output_path}")


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
        outputs=[ct.TensorType(name="scores"), ct.TensorType(name="boxes")],
        minimum_deployment_target=ct.target.iOS16,
        convert_to="mlprogram",
    )
    coreml_model.short_description = (
        "D-FINE mosquito detector for Mosquito Finder. Outputs: scores and normalized boxes."
    )
    coreml_model.save(str(output_path))
    print(f"CoreML written to: {output_path}")


def main() -> None:
    args = build_parser().parse_args()
    args.config = args.config.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.onnx_output = args.onnx_output.resolve()
    args.mlmodel_output = args.mlmodel_output.resolve()
    os.chdir(DFINE_ROOT)
    model = load_dfine_model(args.config, args.checkpoint, args.raw_outputs)
    if not args.skip_onnx:
        export_onnx(model, args.onnx_output, args.image_size)
    if not args.skip_coreml:
        export_coreml(model, args.mlmodel_output, args.image_size)


if __name__ == "__main__":
    main()
