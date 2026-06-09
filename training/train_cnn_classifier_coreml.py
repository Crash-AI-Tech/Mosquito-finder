#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "artifacts" / "classifier_real_detector_crops" / "manifest.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "retrain_real" / "classifier_cnn_real"
CLASS_LABELS = ["not_mosquito", "mosquito"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a real-data RGB CNN Stage-2 mosquito classifier and export CoreML."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--image-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=768)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--negative-weight", type=float, default=1.0)
    parser.add_argument("--positive-weight", type=float, default=1.0)
    parser.add_argument("--train-splits", nargs="+", default=["train2017"])
    parser.add_argument("--eval-splits", nargs="+", default=["val2017"])
    parser.add_argument("--thresholds", default="0.30,0.40,0.50,0.60,0.70,0.80,0.90,0.95")
    parser.add_argument("--selection-min-precision", type=float, default=0.90)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--torch-threads", type=int, default=None)
    parser.add_argument("--seed", type=int, default=20260610)
    parser.add_argument("--export-coreml", action="store_true")
    parser.add_argument(
        "--export-only-checkpoint",
        type=Path,
        default=None,
        help="Skip training and export this checkpoint to CoreML.",
    )
    parser.add_argument(
        "--coreml-output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "MosquitoClassifierCNN.mlmodel",
    )
    return parser


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(requested)


def sync_device(device: torch.device) -> None:
    if device.type == "mps":
        torch.mps.synchronize()


def load_records(manifest_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            row["binary_label"] = int(row["binary_label"])
            records.append(row)
    return records


class CropDataset(Dataset):
    def __init__(
        self,
        records: list[dict[str, Any]],
        image_size: int,
        augment: bool,
    ) -> None:
        self.records = records
        train_ops = [
            transforms.Resize((image_size, image_size)),
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.RandomVerticalFlip(p=0.2),
            transforms.RandomApply(
                [transforms.ColorJitter(brightness=0.25, contrast=0.25, saturation=0.18, hue=0.04)],
                p=0.45,
            ),
            transforms.RandomAffine(
                degrees=12,
                translate=(0.08, 0.08),
                scale=(0.88, 1.14),
                fill=(128, 128, 128),
            ),
            transforms.ToTensor(),
        ]
        eval_ops = [
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
        ]
        self.transform = transforms.Compose(train_ops if augment else eval_ops)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        record = self.records[index]
        image_path = REPO_ROOT / record["relative_path"]
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        tensor = self.transform(image)
        label = torch.tensor(int(record["binary_label"]), dtype=torch.long)
        return tensor, label


class ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.SiLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class TinyMosquitoCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            ConvBlock(3, 32),
            ConvBlock(32, 32),
            nn.MaxPool2d(2),
            ConvBlock(32, 64),
            ConvBlock(64, 64),
            nn.MaxPool2d(2),
            ConvBlock(64, 128),
            ConvBlock(128, 128),
            nn.MaxPool2d(2),
            ConvBlock(128, 192),
            ConvBlock(192, 192),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(p=0.25),
            nn.Linear(192, 2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    thresholds: list[float],
) -> dict[str, Any]:
    model.eval()
    probabilities: list[np.ndarray] = []
    labels: list[np.ndarray] = []

    for images, targets in loader:
        images = images.to(device)
        logits = model(images)
        scores = torch.softmax(logits, dim=1)[:, 1]
        probabilities.append(scores.detach().cpu().numpy())
        labels.append(targets.numpy())

    y_score = np.concatenate(probabilities)
    y_true = np.concatenate(labels).astype(np.int32)
    metrics = []
    for threshold in thresholds:
        y_pred = y_score >= threshold
        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())
        tn = int(((y_pred == 0) & (y_true == 0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        accuracy = (tp + tn) / max(1, len(y_true))
        f1 = 2 * precision * recall / max(1e-9, precision + recall)
        metrics.append(
            {
                "threshold": threshold,
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "true_positive": tp,
                "false_positive": fp,
                "true_negative": tn,
                "false_negative": fn,
            }
        )

    best_f1 = max(metrics, key=lambda item: item["f1"])
    return {
        "samples": int(len(y_true)),
        "positives": int(y_true.sum()),
        "negatives": int((y_true == 0).sum()),
        "positive_quantiles": np.quantile(
            y_score[y_true == 1], [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]
        ).round(6).tolist() if int(y_true.sum()) else [],
        "negative_quantiles": np.quantile(
            y_score[y_true == 0], [0, 0.5, 0.75, 0.9, 0.95, 0.99, 1]
        ).round(6).tolist() if int((y_true == 0).sum()) else [],
        "best_f1": best_f1,
        "metrics": metrics,
    }


def selection_score(metrics: dict[str, Any], min_precision: float) -> tuple[float, float, float]:
    candidates = [
        item for item in metrics["metrics"]
        if item["precision"] >= min_precision
    ]
    if candidates:
        best = max(candidates, key=lambda item: (item["recall"], item["f1"]))
        return 1.0, float(best["recall"]), float(best["f1"])
    best_f1 = metrics["best_f1"]
    return 0.0, float(best_f1["f1"]), float(best_f1["recall"])


def export_coreml(model: nn.Module, image_size: int, output_path: Path) -> None:
    import coremltools as ct

    class ProbabilityWrapper(nn.Module):
        def __init__(self, wrapped: nn.Module) -> None:
            super().__init__()
            self.wrapped = wrapped

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return torch.softmax(self.wrapped(x), dim=1)

    wrapped = ProbabilityWrapper(model.cpu().eval()).eval()
    example = torch.rand(1, 3, image_size, image_size)
    traced = torch.jit.trace(wrapped, example)
    classifier_config = ct.ClassifierConfig(CLASS_LABELS)
    image_input = ct.ImageType(
        name="image",
        shape=example.shape,
        scale=1.0 / 255.0,
        color_layout=ct.colorlayout.RGB,
    )
    mlmodel = ct.convert(
        traced,
        inputs=[image_input],
        classifier_config=classifier_config,
        convert_to="neuralnetwork",
        minimum_deployment_target=ct.target.iOS14,
    )
    mlmodel.short_description = "Mosquito Finder Stage-2 RGB CNN classifier."
    mlmodel.author = "Mosquito Finder ML Pipeline"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mlmodel.save(str(output_path))


def main() -> int:
    args = build_parser().parse_args()
    seed_everything(args.seed)
    if args.torch_threads is not None:
        torch.set_num_threads(args.torch_threads)

    args.manifest = args.manifest.resolve()
    args.output_dir = args.output_dir.resolve()
    args.coreml_output = args.coreml_output.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.export_only_checkpoint:
        checkpoint = torch.load(
            args.export_only_checkpoint.resolve(),
            map_location="cpu",
            weights_only=False,
        )
        model = TinyMosquitoCNN()
        model.load_state_dict(checkpoint["model"])
        export_coreml(model, args.image_size, args.coreml_output)
        print(f"coreml={args.coreml_output}", flush=True)
        return 0

    records = [record for record in load_records(args.manifest) if record["binary_label"] >= 0]
    train_records = [record for record in records if record.get("split") in set(args.train_splits)]
    eval_records = [record for record in records if record.get("split") in set(args.eval_splits)]
    if not train_records or not eval_records:
        raise ValueError("No train/eval records selected. Check split names.")

    train_dataset = CropDataset(train_records, args.image_size, augment=True)
    eval_dataset = CropDataset(eval_records, args.image_size, augment=False)
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=False,
        persistent_workers=args.num_workers > 0,
    )
    eval_loader = DataLoader(
        eval_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=False,
        persistent_workers=args.num_workers > 0,
    )

    device = choose_device(args.device)
    model = TinyMosquitoCNN().to(device)
    class_weights = torch.tensor(
        [args.negative_weight, args.positive_weight],
        dtype=torch.float32,
        device=device,
    )
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))
    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]

    started = time.perf_counter()
    best_score: tuple[float, float, float] | None = None
    best_metrics: dict[str, Any] | None = None
    best_epoch = 0

    print(
        json.dumps(
            {
                "device": str(device),
                "train_samples": len(train_records),
                "eval_samples": len(eval_records),
                "batch_size": args.batch_size,
                "epochs": args.epochs,
                "num_workers": args.num_workers,
            },
            indent=2,
        ),
        flush=True,
    )

    for epoch in range(1, args.epochs + 1):
        model.train()
        loss_values: list[float] = []
        epoch_started = time.perf_counter()
        for images, targets in train_loader:
            images = images.to(device)
            targets = targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()
            loss_values.append(float(loss.detach().cpu()))
        sync_device(device)
        scheduler.step()

        metrics = evaluate(model, eval_loader, device, thresholds)
        score = selection_score(metrics, args.selection_min_precision)
        is_best = best_score is None or score > best_score
        if is_best:
            best_score = score
            best_metrics = metrics
            best_epoch = epoch
            torch.save(
                {
                    "model": model.state_dict(),
                    "epoch": epoch,
                    "metrics": metrics,
                    "args": vars(args),
                    "class_labels": CLASS_LABELS,
                },
                args.output_dir / "best.pt",
            )

        print(
            "epoch={}/{} loss={:.6f} best_f1={:.3f} best_precision={:.3f} "
            "best_recall={:.3f} elapsed={:.1f}s{}".format(
                epoch,
                args.epochs,
                float(np.mean(loss_values)),
                metrics["best_f1"]["f1"],
                metrics["best_f1"]["precision"],
                metrics["best_f1"]["recall"],
                time.perf_counter() - epoch_started,
                " best" if is_best else "",
            ),
            flush=True,
        )

    elapsed = time.perf_counter() - started
    torch.save(
        {
            "model": model.state_dict(),
            "epoch": args.epochs,
            "metrics": metrics,
            "args": vars(args),
            "class_labels": CLASS_LABELS,
        },
        args.output_dir / "latest.pt",
    )
    if best_metrics is None:
        raise RuntimeError("Training finished without producing metrics.")

    summary = {
        "device": str(device),
        "train_samples": len(train_records),
        "eval_samples": len(eval_records),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "num_workers": args.num_workers,
        "best_epoch": best_epoch,
        "selection_min_precision": args.selection_min_precision,
        "best_metrics": best_metrics,
        "elapsed_seconds": elapsed,
        "best_checkpoint": str(args.output_dir / "best.pt"),
        "latest_checkpoint": str(args.output_dir / "latest.pt"),
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.export_coreml:
        checkpoint = torch.load(args.output_dir / "best.pt", map_location="cpu", weights_only=False)
        model.load_state_dict(checkpoint["model"])
        export_coreml(model, args.image_size, args.coreml_output)
        summary["coreml_output"] = str(args.coreml_output)
        (args.output_dir / "metrics.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"coreml={args.coreml_output}", flush=True)

    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
