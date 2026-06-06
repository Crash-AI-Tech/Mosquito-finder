#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
YOLOX_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "YOLOX"

if str(YOLOX_ROOT) not in sys.path:
    sys.path.insert(0, str(YOLOX_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yolox.data.data_augment import ValTransform  # noqa: E402
from yolox.utils import postprocess  # noqa: E402


@dataclass
class Detection:
    image_id: int
    score: float
    box: np.ndarray


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate YOLOX detector precision/recall on COCO annotations.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--exp-module", default="training.yolox_kaggle_smoke")
    parser.add_argument(
        "--ann-file",
        default=str(
            REPO_ROOT
            / "data"
            / "processed"
            / "kaggle_coco_single_class"
            / "annotations"
            / "instances_val2017.json"
        ),
    )
    parser.add_argument(
        "--image-dir",
        default=str(REPO_ROOT / "data" / "processed" / "kaggle_coco_single_class" / "val2017"),
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--num-images", type=int, default=0)
    parser.add_argument("--nms", type=float, default=0.45)
    parser.add_argument("--base-conf", type=float, default=0.01)
    parser.add_argument("--iou-threshold", type=float, default=0.5)
    parser.add_argument(
        "--thresholds",
        default="0.05,0.10,0.20,0.30,0.35,0.40,0.50,0.60,0.70,0.78,0.85,0.90",
    )
    return parser


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(requested)


def xywh_to_xyxy(box: list[float]) -> np.ndarray:
    x, y, width, height = box
    return np.array([x, y, x + width, y + height], dtype=np.float32)


def box_iou(box: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    if boxes.size == 0:
        return np.zeros((0,), dtype=np.float32)
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    box_area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
    areas = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0, boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(box_area + areas - inter, 1e-6)


def load_model(checkpoint_path: Path, device: torch.device, exp_module: str) -> tuple[object, torch.nn.Module]:
    exp = importlib.import_module(exp_module).Exp()
    model = exp.get_model().to(device)
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    model.load_state_dict(checkpoint["model"] if "model" in checkpoint else checkpoint)
    model.eval()
    return exp, model


def collect_detections(
    exp: Exp,
    model: torch.nn.Module,
    images: list[dict[str, object]],
    image_dir: Path,
    device: torch.device,
    base_conf: float,
    nms: float,
) -> list[Detection]:
    transform = ValTransform(legacy=False)
    detections: list[Detection] = []

    with torch.no_grad():
        for image_meta in images:
            image_path = image_dir / str(image_meta["file_name"])
            image = cv2.imread(str(image_path))
            if image is None:
                raise FileNotFoundError(image_path)

            tensor, _ = transform(image, None, exp.test_size)
            tensor = torch.from_numpy(tensor).unsqueeze(0).float().to(device)
            outputs = model(tensor)
            outputs = postprocess(outputs, exp.num_classes, base_conf, nms, class_agnostic=True)

            if outputs[0] is None:
                continue

            ratio = min(exp.test_size[0] / image.shape[0], exp.test_size[1] / image.shape[1])
            output = outputs[0].detach().cpu().numpy()
            boxes = output[:, :4] / ratio
            scores = output[:, 4] * output[:, 5]
            for box, score in zip(boxes, scores):
                detections.append(Detection(int(image_meta["id"]), float(score), box.astype(np.float32)))

    return detections


def evaluate_at_threshold(
    detections: list[Detection],
    gt_by_image: dict[int, np.ndarray],
    threshold: float,
    iou_threshold: float,
) -> dict[str, float | int]:
    filtered = [detection for detection in detections if detection.score >= threshold]
    filtered.sort(key=lambda detection: detection.score, reverse=True)

    matched: dict[int, set[int]] = {image_id: set() for image_id in gt_by_image}
    true_positive = 0
    false_positive = 0

    for detection in filtered:
        gt_boxes = gt_by_image.get(detection.image_id, np.zeros((0, 4), dtype=np.float32))
        ious = box_iou(detection.box, gt_boxes)
        if ious.size == 0:
            false_positive += 1
            continue

        best_index = int(np.argmax(ious))
        if ious[best_index] >= iou_threshold and best_index not in matched.setdefault(detection.image_id, set()):
            true_positive += 1
            matched[detection.image_id].add(best_index)
        else:
            false_positive += 1

    total_gt = sum(len(boxes) for boxes in gt_by_image.values())
    false_negative = max(0, total_gt - true_positive)
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)

    detected_images = {detection.image_id for detection in filtered}
    images_with_gt = {image_id for image_id, boxes in gt_by_image.items() if len(boxes) > 0}
    image_hit_count = sum(1 for image_id in images_with_gt if matched.get(image_id))

    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "detections": len(filtered),
        "image_hit_rate": image_hit_count / max(1, len(images_with_gt)),
        "image_hit_count": image_hit_count,
        "images_with_detections": len(detected_images),
    }


def main() -> int:
    args = build_parser().parse_args()
    ann_data = json.loads(Path(args.ann_file).read_text(encoding="utf-8"))
    images = ann_data["images"][: args.num_images] if args.num_images > 0 else ann_data["images"]
    image_ids = {int(image["id"]) for image in images}

    gt_by_image: dict[int, list[np.ndarray]] = {image_id: [] for image_id in image_ids}
    for annotation in ann_data["annotations"]:
        image_id = int(annotation["image_id"])
        if image_id in image_ids:
            gt_by_image.setdefault(image_id, []).append(xywh_to_xyxy(annotation["bbox"]))
    gt_arrays = {
        image_id: np.array(boxes, dtype=np.float32).reshape((-1, 4))
        for image_id, boxes in gt_by_image.items()
    }

    device = choose_device(args.device)
    exp, model = load_model(Path(args.checkpoint), device, args.exp_module)
    detections = collect_detections(
        exp=exp,
        model=model,
        images=images,
        image_dir=Path(args.image_dir),
        device=device,
        base_conf=args.base_conf,
        nms=args.nms,
    )

    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    metrics = [evaluate_at_threshold(detections, gt_arrays, threshold, args.iou_threshold) for threshold in thresholds]
    target_candidates = [
        metric for metric in metrics if metric["precision"] >= 0.95
    ]
    best_high_precision = max(target_candidates, key=lambda metric: (metric["recall"], metric["f1"]), default=None)
    best_f1 = max(metrics, key=lambda metric: metric["f1"], default=None)

    summary = {
        "checkpoint": args.checkpoint,
        "ann_file": args.ann_file,
        "image_dir": args.image_dir,
        "device": str(device),
        "num_images": len(images),
        "ground_truth_boxes": int(sum(len(boxes) for boxes in gt_arrays.values())),
        "base_conf": args.base_conf,
        "nms": args.nms,
        "iou_threshold": args.iou_threshold,
        "raw_detections": len(detections),
        "best_high_precision": best_high_precision,
        "best_f1": best_f1,
        "metrics": metrics,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
