#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import coremltools as ct
import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "Mosquito-finder" / "DfineMosquitoDetector.mlpackage"
DEFAULT_ANN_FILE = (
    REPO_ROOT
    / "data"
    / "processed"
    / "combined_mosquito_coco_single_class"
    / "annotations"
    / "instances_val2017.json"
)
DEFAULT_IMAGE_DIR = REPO_ROOT / "data" / "processed" / "combined_mosquito_coco_single_class" / "val2017"


@dataclass
class Detection:
    image_id: int
    score: float
    box: np.ndarray


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate D-FINE CoreML detector on COCO boxes.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--ann-file", type=Path, default=DEFAULT_ANN_FILE)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-size", type=int, default=416)
    parser.add_argument("--base-conf", type=float, default=0.01)
    parser.add_argument("--nms", type=float, default=0.35)
    parser.add_argument("--max-boxes", type=int, default=100)
    parser.add_argument("--max-area-ratio", type=float, default=0.30)
    parser.add_argument("--min-box-size", type=float, default=2.0)
    parser.add_argument("--iou-threshold", type=float, default=0.50)
    parser.add_argument(
        "--thresholds",
        default="0.05,0.10,0.20,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75,0.80",
    )
    parser.add_argument("--num-images", type=int, default=0)
    return parser


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
    box_area = max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))
    areas = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0, boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(box_area + areas - inter, 1e-6)


def nms(detections: list[Detection], iou_threshold: float, max_boxes: int) -> list[Detection]:
    selected: list[Detection] = []
    remaining = sorted(detections, key=lambda item: item.score, reverse=True)
    while remaining and len(selected) < max_boxes:
        current = remaining.pop(0)
        selected.append(current)
        if not remaining:
            break
        boxes = np.vstack([item.box for item in remaining]).astype(np.float32)
        keep = box_iou(current.box, boxes) < iou_threshold
        remaining = [item for item, should_keep in zip(remaining, keep) if bool(should_keep)]
    return selected


def parse_outputs(
    outputs: dict[str, Any],
    image_id: int,
    image_width: int,
    image_height: int,
    base_conf: float,
    min_box_size: float,
    max_area_ratio: float,
) -> list[Detection]:
    score_output = next(value for key, value in outputs.items() if "score" in key.lower())
    box_output = next(value for key, value in outputs.items() if "box" in key.lower())
    scores = np.asarray(score_output, dtype=np.float32).reshape(-1)
    boxes = np.asarray(box_output, dtype=np.float32).reshape((-1, 4))
    image_area = float(image_width * image_height)
    detections: list[Detection] = []

    for score, raw_box in zip(scores, boxes):
        if float(score) < base_conf:
            continue
        cx, cy, width, height = [float(value) for value in raw_box]
        x1 = max(0.0, (cx - width / 2.0) * image_width)
        y1 = max(0.0, (cy - height / 2.0) * image_height)
        x2 = min(float(image_width), (cx + width / 2.0) * image_width)
        y2 = min(float(image_height), (cy + height / 2.0) * image_height)
        box = np.array([x1, y1, x2, y2], dtype=np.float32)
        box_width = max(0.0, float(x2 - x1))
        box_height = max(0.0, float(y2 - y1))
        if box_width < min_box_size or box_height < min_box_size:
            continue
        if box_width * box_height / max(image_area, 1.0) > max_area_ratio:
            continue
        detections.append(Detection(image_id=image_id, score=float(score), box=box))
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
    image_hit_count = sum(1 for image_id, boxes in gt_by_image.items() if len(boxes) and matched.get(image_id))

    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "detections": len(filtered),
        "image_hit_rate": image_hit_count / max(1, sum(1 for boxes in gt_by_image.values() if len(boxes))),
        "image_hit_count": image_hit_count,
    }


def main() -> int:
    args = build_parser().parse_args()
    ann_data = json.loads(args.ann_file.read_text(encoding="utf-8"))
    images = ann_data["images"][: args.num_images] if args.num_images > 0 else ann_data["images"]
    image_ids = {int(image["id"]) for image in images}
    gt_by_image_list: dict[int, list[np.ndarray]] = {image_id: [] for image_id in image_ids}
    for annotation in ann_data["annotations"]:
        image_id = int(annotation["image_id"])
        if image_id in image_ids:
            gt_by_image_list.setdefault(image_id, []).append(xywh_to_xyxy(annotation["bbox"]))
    gt_by_image = {
        image_id: np.array(boxes, dtype=np.float32).reshape((-1, 4))
        for image_id, boxes in gt_by_image_list.items()
    }

    model = ct.models.MLModel(str(args.model))
    detections: list[Detection] = []
    for image_meta in images:
        image_id = int(image_meta["id"])
        image_path = args.image_dir / str(image_meta["file_name"])
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        model_input = image.resize((args.image_size, args.image_size), Image.Resampling.BILINEAR)
        outputs = model.predict({"images": model_input})
        image_detections = parse_outputs(
            outputs,
            image_id,
            image.width,
            image.height,
            args.base_conf,
            args.min_box_size,
            args.max_area_ratio,
        )
        detections.extend(nms(image_detections, args.nms, args.max_boxes))

    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    metrics = [evaluate_at_threshold(detections, gt_by_image, threshold, args.iou_threshold) for threshold in thresholds]
    high_precision = [metric for metric in metrics if metric["precision"] >= 0.95]
    summary = {
        "model": str(args.model),
        "ann_file": str(args.ann_file),
        "image_dir": str(args.image_dir),
        "num_images": len(images),
        "ground_truth_boxes": int(sum(len(boxes) for boxes in gt_by_image.values())),
        "raw_detections": len(detections),
        "base_conf": args.base_conf,
        "nms": args.nms,
        "iou_threshold": args.iou_threshold,
        "best_f1": max(metrics, key=lambda item: item["f1"], default=None),
        "best_high_precision": max(high_precision, key=lambda item: (item["recall"], item["f1"]), default=None),
        "metrics": metrics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
