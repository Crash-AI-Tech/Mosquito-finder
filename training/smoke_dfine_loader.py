#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
DFINE_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "D-FINE"

if str(DFINE_ROOT) not in sys.path:
    sys.path.insert(0, str(DFINE_ROOT))

from src.core import YAMLConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a one-batch D-FINE dataloader smoke check."
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "training" / "dfine_kaggle_smoke.yml"),
    )
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    cfg = YAMLConfig(args.config, device=args.device)
    images, targets = next(iter(cfg.train_dataloader))

    print(f"device={args.device}")
    print(f"image_shape={tuple(images.shape)}")
    print(f"target_count={len(targets)}")
    print("target_keys=" + ",".join(sorted(targets[0].keys())))
    print(f"boxes_shape={tuple(targets[0]['boxes'].shape)}")
    print(f"labels_shape={tuple(targets[0]['labels'].shape)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
