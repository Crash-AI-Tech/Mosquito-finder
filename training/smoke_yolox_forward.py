#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
YOLOX_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "YOLOX"

if str(YOLOX_ROOT) not in sys.path:
    sys.path.insert(0, str(YOLOX_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from training.yolox_kaggle_smoke import Exp  # noqa: E402


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(requested)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a one-batch YOLOX forward/backward smoke check."
    )
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument(
        "--device",
        choices=("cpu", "mps", "auto"),
        default="cpu",
        help="Default is CPU because upstream YOLOX training is CUDA-oriented.",
    )
    args = parser.parse_args()

    device = choose_device(args.device)
    exp = Exp()

    loader = exp.get_data_loader(
        batch_size=args.batch_size,
        is_distributed=False,
        no_aug=True,
        cache_img=None,
    )
    model = exp.get_model().to(device)
    model.train()
    optimizer = torch.optim.SGD(model.parameters(), lr=1e-5, momentum=0.9)

    inputs, targets, *_ = next(iter(loader))
    inputs = inputs.float().to(device)
    targets = targets.float().to(device)
    inputs, targets = exp.preprocess(inputs, targets, exp.input_size)

    optimizer.zero_grad(set_to_none=True)
    outputs = model(inputs, targets)
    loss = outputs["total_loss"]
    loss.backward()
    optimizer.step()

    print(f"device={device}")
    print(f"batch_input_shape={tuple(inputs.shape)}")
    print(f"batch_target_shape={tuple(targets.shape)}")
    print(f"loss={float(loss.detach().cpu()):.6f}")
    print("loss_keys=" + ",".join(sorted(outputs.keys())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
