#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

import torch


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
YOLOX_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "YOLOX"

if str(YOLOX_ROOT) not in sys.path:
    sys.path.insert(0, str(YOLOX_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(requested)


def sync_device(device: torch.device) -> None:
    if device.type == "mps":
        torch.mps.synchronize()


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
    exp_name: str,
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
            "exp": exp_name,
        },
        checkpoint_path,
    )
    return checkpoint_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a small YOLOX training loop on CPU or Apple MPS."
    )
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--print-every", type=int, default=1)
    parser.add_argument("--checkpoint-every", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=None)
    parser.add_argument("--cache-img", choices=("none", "ram", "disk"), default="none")
    parser.add_argument("--lr", type=float, default=1e-5)
    parser.add_argument("--exp-module", default="training.yolox_kaggle_smoke")
    parser.add_argument("--resume", default=None)
    parser.add_argument(
        "--freeze-backbone",
        action="store_true",
        help="Freeze YOLOX backbone/FPN and train only the detection head.",
    )
    parser.add_argument(
        "--resume-optimizer",
        action="store_true",
        help="Restore optimizer state from the checkpoint. By default, only model weights are restored.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "artifacts" / "yolox_mps_smoke"),
    )
    args = parser.parse_args()

    device = choose_device(args.device)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exp = importlib.import_module(args.exp_module).Exp()
    if args.num_workers is not None:
        exp.data_num_workers = args.num_workers
    if args.cache_img != "none":
        exp.dataset = exp.get_dataset(cache=True, cache_type=args.cache_img)
    loader = exp.get_data_loader(
        batch_size=args.batch_size,
        is_distributed=False,
        no_aug=True,
        cache_img=args.cache_img if args.cache_img != "none" else None,
    )
    model = exp.get_model().to(device)
    model.train()
    if args.freeze_backbone:
        for parameter in model.backbone.parameters():
            parameter.requires_grad = False

    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    if not trainable_parameters:
        raise RuntimeError("No trainable parameters remain after applying freeze options.")

    optimizer = torch.optim.SGD(trainable_parameters, lr=args.lr, momentum=0.9)
    resumed_steps = 0

    if args.resume:
        checkpoint = torch.load(args.resume, map_location="cpu")
        model.load_state_dict(checkpoint["model"])
        if args.resume_optimizer and "optimizer" in checkpoint:
            optimizer.load_state_dict(checkpoint["optimizer"])
            for state in optimizer.state.values():
                for key, value in state.items():
                    if isinstance(value, torch.Tensor):
                        state[key] = value.to(device)
        resumed_steps = int(checkpoint.get("total_steps", checkpoint.get("steps", 0)))
        print(f"resumed_from={args.resume}", flush=True)
        print(f"resumed_steps={resumed_steps}", flush=True)

    data_iter = iter(loader)
    started_at = time.perf_counter()
    last_loss = None

    for step in range(1, args.steps + 1):
        try:
            inputs, targets, *_ = next(data_iter)
        except StopIteration:
            data_iter = iter(loader)
            inputs, targets, *_ = next(data_iter)

        inputs = inputs.float().to(device)
        targets = targets.float().to(device)
        inputs, targets = exp.preprocess(inputs, targets, exp.input_size)

        optimizer.zero_grad(set_to_none=True)
        outputs = model(inputs, targets)
        loss = outputs["total_loss"]
        loss.backward()
        optimizer.step()
        sync_device(device)

        last_loss = float(loss.detach().cpu())
        if step == 1 or step == args.steps or step % args.print_every == 0:
            print(f"step={step}/{args.steps} loss={last_loss:.6f}", flush=True)

        if args.checkpoint_every > 0 and step % args.checkpoint_every == 0:
            elapsed = time.perf_counter() - started_at
            checkpoint_path = save_checkpoint(
                output_dir=output_dir,
                name=f"step_{resumed_steps + step}.pt",
                model=model,
                optimizer=optimizer,
                args=args,
                device=device,
                resumed_steps=resumed_steps,
                completed_steps=step,
                last_loss=last_loss,
                elapsed=elapsed,
                exp_name=exp.exp_name,
            )
            print(f"checkpoint={checkpoint_path}", flush=True)

    elapsed = time.perf_counter() - started_at
    checkpoint_path = save_checkpoint(
        output_dir=output_dir,
        name="latest.pt",
        model=model,
        optimizer=optimizer,
        args=args,
        device=device,
        resumed_steps=resumed_steps,
        completed_steps=args.steps,
        last_loss=last_loss,
        elapsed=elapsed,
        exp_name=exp.exp_name,
    )

    summary = {
        "device": str(device),
        "batch_size": args.batch_size,
        "steps": args.steps,
        "total_steps": resumed_steps + args.steps,
        "print_every": args.print_every,
        "checkpoint_every": args.checkpoint_every,
        "num_workers": exp.data_num_workers,
        "cache_img": args.cache_img,
        "freeze_backbone": args.freeze_backbone,
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
    print(f"total_steps={resumed_steps + args.steps}", flush=True)
    print(f"elapsed_seconds={elapsed:.3f}", flush=True)
    print(f"seconds_per_step={elapsed / args.steps:.3f}", flush=True)
    print(f"checkpoint={checkpoint_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
