#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
from torch import nn


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
DFINE_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "D-FINE"

if str(DFINE_ROOT) not in sys.path:
    sys.path.insert(0, str(DFINE_ROOT))

from src.core import YAMLConfig  # noqa: E402


class MpsFriendlyIntegral(nn.Module):
    def __init__(self, reg_max: int) -> None:
        super().__init__()
        self.reg_max = reg_max

    def forward(self, x: torch.Tensor, project: torch.Tensor) -> torch.Tensor:
        shape = x.shape
        x = torch.softmax(x.reshape(-1, self.reg_max + 1), dim=1)
        weights = project.to(x.device).reshape(1, self.reg_max + 1)
        x = (x * weights).sum(dim=1, keepdim=True).reshape(-1, 4)
        return x.reshape(list(shape[:-1]) + [-1])


def move_targets_to_device(targets: list[dict], device: torch.device) -> list[dict]:
    return [
        {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in target.items()}
        for target in targets
    ]


def load_checkpoint(
    checkpoint_path: Path,
    model: torch.nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
    resume_optimizer: bool,
) -> dict:
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise TypeError(f"Unsupported checkpoint format: {checkpoint_path}")

    if "ema" in checkpoint and isinstance(checkpoint["ema"], dict) and "module" in checkpoint["ema"]:
        state = checkpoint["ema"]["module"]
    elif "model" in checkpoint:
        state = checkpoint["model"]
    else:
        state = checkpoint
    model.load_state_dict(state)

    if resume_optimizer and "optimizer" in checkpoint:
        optimizer.load_state_dict(checkpoint["optimizer"])
        for state_value in optimizer.state.values():
            for key, value in state_value.items():
                if isinstance(value, torch.Tensor):
                    state_value[key] = value.to(device)

    return checkpoint


def save_checkpoint(
    output_dir: Path,
    name: str,
    model: torch.nn.Module,
    optimizer: torch.optim.Optimizer,
    args: argparse.Namespace,
    device: torch.device,
    resumed_steps: int,
    completed_steps: int,
    last_loss: float | None,
    elapsed: float,
) -> Path:
    checkpoint_path = output_dir / name
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "steps": completed_steps,
            "total_steps": resumed_steps + completed_steps,
            "device": str(device),
            "last_loss": last_loss,
            "elapsed_seconds": elapsed,
            "config": args.config,
            "resume": args.resume,
        },
        checkpoint_path,
    )
    return checkpoint_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a limited D-FINE training loop for smoke verification."
    )
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "training" / "dfine_kaggle_smoke.yml"),
    )
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--torch-threads", type=int, default=None)
    parser.add_argument("--num-workers", type=int, default=None)
    parser.add_argument("--mps-friendly-integral", action="store_true")
    parser.add_argument("--resume", default=None)
    parser.add_argument("--resume-optimizer", action="store_true")
    parser.add_argument("--checkpoint-every", type=int, default=0)
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / "dfine_cpu_smoke"),
    )
    args = parser.parse_args()

    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)

    device = torch.device(args.device)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = YAMLConfig(args.config, device=str(device))
    if args.batch_size is not None:
        cfg.yaml_cfg["train_dataloader"]["total_batch_size"] = args.batch_size
    if args.num_workers is not None:
        cfg.yaml_cfg["train_dataloader"]["num_workers"] = args.num_workers
    if args.mps_friendly_integral:
        cfg.model.decoder.integral = MpsFriendlyIntegral(cfg.model.decoder.reg_max)
    model = cfg.model.to(device)
    criterion = cfg.criterion.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    resumed_steps = 0
    if args.resume:
        checkpoint = load_checkpoint(
            Path(args.resume),
            model,
            optimizer,
            device,
            resume_optimizer=args.resume_optimizer,
        )
        resumed_steps = int(checkpoint.get("total_steps", checkpoint.get("steps", 0)))
        print(f"resumed_from={args.resume}", flush=True)
        print(f"resumed_steps={resumed_steps}", flush=True)

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

        if args.checkpoint_every > 0 and step % args.checkpoint_every == 0:
            elapsed = time.perf_counter() - started_at
            checkpoint_path = save_checkpoint(
                output_dir,
                f"step_{resumed_steps + step}.pth",
                model,
                optimizer,
                args,
                device,
                resumed_steps,
                step,
                last_loss,
                elapsed,
            )
            print(f"checkpoint={checkpoint_path}", flush=True)

    elapsed = time.perf_counter() - started_at
    checkpoint_path = save_checkpoint(
        output_dir,
        "latest.pth",
        model,
        optimizer,
        args,
        device,
        resumed_steps,
        args.steps,
        last_loss,
        elapsed,
    )

    summary = {
        "device": str(device),
        "batch_size": args.batch_size,
        "steps": args.steps,
        "total_steps": resumed_steps + args.steps,
        "last_loss": last_loss,
        "elapsed_seconds": elapsed,
        "seconds_per_step": elapsed / args.steps,
        "checkpoint": str(checkpoint_path),
        "resume": args.resume,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"device={device}", flush=True)
    print(f"steps={args.steps}", flush=True)
    print(f"total_steps={resumed_steps + args.steps}", flush=True)
    print(f"elapsed_seconds={elapsed:.3f}", flush=True)
    print(f"seconds_per_step={elapsed / args.steps:.3f}", flush=True)
    print(f"checkpoint={checkpoint_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
