#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
DFINE_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "D-FINE"

if str(DFINE_ROOT) not in sys.path:
    sys.path.insert(0, str(DFINE_ROOT))

from src.core import YAMLConfig  # noqa: E402


def move_targets_to_device(targets: list[dict], device: torch.device) -> list[dict]:
    return [
        {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in target.items()}
        for target in targets
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a limited D-FINE CPU training loop for smoke verification."
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "training" / "dfine_kaggle_smoke.yml"),
    )
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / "dfine_cpu_smoke"),
    )
    args = parser.parse_args()

    device = torch.device("cpu")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = YAMLConfig(args.config, device=str(device))
    model = cfg.model.to(device)
    criterion = cfg.criterion.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    model.train()
    criterion.train()

    data_iter = iter(cfg.train_dataloader)
    started_at = time.perf_counter()
    last_loss = None

    for step in range(1, args.steps + 1):
        try:
            samples, targets = next(data_iter)
        except StopIteration:
            data_iter = iter(cfg.train_dataloader)
            samples, targets = next(data_iter)

        samples = samples.to(device)
        targets = move_targets_to_device(targets, device)

        optimizer.zero_grad(set_to_none=True)
        outputs = model(samples, targets=targets)
        loss_dict = criterion(
            outputs,
            targets,
            epoch=0,
            step=step - 1,
            global_step=step - 1,
            epoch_step=len(cfg.train_dataloader),
        )
        loss = sum(loss_dict.values())
        loss.backward()
        optimizer.step()

        last_loss = float(loss.detach().cpu())
        print(f"step={step}/{args.steps} loss={last_loss:.6f}", flush=True)

    elapsed = time.perf_counter() - started_at
    checkpoint_path = output_dir / "latest.pth"
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "steps": args.steps,
            "device": str(device),
            "last_loss": last_loss,
            "elapsed_seconds": elapsed,
            "config": args.config,
        },
        checkpoint_path,
    )

    summary = {
        "device": str(device),
        "steps": args.steps,
        "last_loss": last_loss,
        "elapsed_seconds": elapsed,
        "seconds_per_step": elapsed / args.steps,
        "checkpoint": str(checkpoint_path),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"device={device}", flush=True)
    print(f"steps={args.steps}", flush=True)
    print(f"elapsed_seconds={elapsed:.3f}", flush=True)
    print(f"seconds_per_step={elapsed / args.steps:.3f}", flush=True)
    print(f"checkpoint={checkpoint_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
