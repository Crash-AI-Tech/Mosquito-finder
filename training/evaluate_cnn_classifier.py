#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from train_cnn_classifier_coreml import (
    CropDataset,
    TinyMosquitoCNN,
    choose_device,
    evaluate,
    load_records,
    seed_everything,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a Stage-2 CNN classifier checkpoint.")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-size", type=int, default=64)
    parser.add_argument("--eval-splits", nargs="+", default=["val2017"])
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--torch-threads", type=int, default=None)
    parser.add_argument(
        "--thresholds",
        default="0.30,0.40,0.50,0.60,0.70,0.80,0.90,0.95,0.97,0.99",
    )
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    seed_everything(args.seed)
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)

    checkpoint = torch.load(args.checkpoint.resolve(), map_location="cpu", weights_only=False)
    model = TinyMosquitoCNN()
    model.load_state_dict(checkpoint["model"])

    records = [
        record
        for record in load_records(args.manifest.resolve())
        if record["binary_label"] >= 0 and record.get("split") in set(args.eval_splits)
    ]
    if not records:
        raise ValueError("No eval records selected. Check manifest and split names.")

    dataset = CropDataset(records, args.image_size, augment=False)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=False,
        persistent_workers=args.num_workers > 0,
    )
    device = choose_device(args.device)
    model = model.to(device)
    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    metrics = evaluate(model, loader, device, thresholds)
    summary = {
        "checkpoint": str(args.checkpoint.resolve()),
        "manifest": str(args.manifest.resolve()),
        "eval_splits": args.eval_splits,
        "device": str(device),
        "samples": len(records),
        "metrics": metrics,
    }
    rendered = json.dumps(summary, indent=2) + "\n"
    if args.output:
        args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output.resolve().write_text(rendered, encoding="utf-8")
    print(rendered, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
