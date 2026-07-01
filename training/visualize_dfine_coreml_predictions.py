#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import coremltools as ct
import numpy as np
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Detection:
    score: float
    box: np.ndarray


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visualize D-FINE CoreML predictions against COCO boxes.")
    parser.add_argument("--model", type=Path, default=REPO_ROOT / "Mosquito-finder" / "DfineMosquitoDetector.mlpackage")
    parser.add_argument("--ann-file", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--phone-image-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-images", type=int, default=240)
    parser.add_argument("--sample-images", type=int, default=48)
    parser.add_argument("--conf", type=float, default=0.01)
    parser.add_argument("--nms", type=float, default=0.42)
    parser.add_argument("--max-predictions", type=int, default=8)
    parser.add_argument("--max-area-ratio", type=float, default=0.30)
    parser.add_argument("--min-box-size", type=float, default=2.0)
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


def nms(detections: list[Detection], iou_threshold: float, max_predictions: int) -> list[Detection]:
    selected: list[Detection] = []
    for detection in sorted(detections, key=lambda item: item.score, reverse=True):
        if selected:
            boxes = np.vstack([item.box for item in selected]).astype(np.float32)
            if float(box_iou(detection.box, boxes).max(initial=0.0)) >= iou_threshold:
                continue
        selected.append(detection)
        if len(selected) >= max_predictions:
            break
    return selected


def parse_outputs(
    outputs: dict[str, Any],
    image_width: int,
    image_height: int,
    conf: float,
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
        if float(score) < conf:
            continue
        cx, cy, width, height = [float(value) for value in raw_box]
        x1 = max(0.0, (cx - width / 2.0) * image_width)
        y1 = max(0.0, (cy - height / 2.0) * image_height)
        x2 = min(float(image_width), (cx + width / 2.0) * image_width)
        y2 = min(float(image_height), (cy + height / 2.0) * image_height)
        box_width = max(0.0, x2 - x1)
        box_height = max(0.0, y2 - y1)
        if box_width < min_box_size or box_height < min_box_size:
            continue
        if box_width * box_height / max(image_area, 1.0) > max_area_ratio:
            continue
        detections.append(Detection(float(score), np.array([x1, y1, x2, y2], dtype=np.float32)))
    return detections


def draw_box(draw: ImageDraw.ImageDraw, box: np.ndarray, color: str, label: str, width: int) -> None:
    x1, y1, x2, y2 = [float(value) for value in box]
    draw.rectangle([x1, y1, x2, y2], outline=color, width=width)
    draw.text((x1, max(0.0, y1 - 14.0)), label, fill=color)


def draw_model_overlay(image: Image.Image, gt_boxes: np.ndarray, detections: list[Detection], output_path: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for gt_box in gt_boxes:
        draw_box(draw, gt_box, "lime", "gt", 2)
    for detection in detections:
        draw_box(draw, detection.box, "magenta", f"dfine {detection.score:.2f}", 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


def draw_phone_overlay(phone_path: Path, annotations: list[dict[str, Any]], output_path: Path) -> None:
    if not phone_path.exists():
        return
    image = Image.open(phone_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for annotation in annotations:
        source_box = annotation.get("source_phone_box")
        if not source_box:
            continue
        x, y, width, height = [float(value) for value in source_box]
        draw_box(draw, np.array([x, y, x + width, y + height], dtype=np.float32), "lime", "phone gt", 4)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=88)


def main() -> int:
    args = build_parser().parse_args()
    ann_data = json.loads(args.ann_file.read_text(encoding="utf-8"))
    images = ann_data["images"][: args.num_images] if args.num_images > 0 else ann_data["images"]
    image_ids = {int(image["id"]) for image in images}
    annotations_by_image: dict[int, list[dict[str, Any]]] = {image_id: [] for image_id in image_ids}
    for annotation in ann_data["annotations"]:
        image_id = int(annotation["image_id"])
        if image_id in image_ids:
            annotations_by_image.setdefault(image_id, []).append(annotation)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model = ct.models.MLModel(str(args.model))
    rows: list[dict[str, Any]] = []
    saved = 0
    hit_iou_03 = 0

    for image_meta in images:
        image_id = int(image_meta["id"])
        image_path = args.image_dir / str(image_meta["file_name"])
        image = Image.open(image_path).convert("RGB")
        outputs = model.predict({"images": image.resize((416, 416), Image.Resampling.BILINEAR)})
        detections = nms(
            parse_outputs(outputs, image.width, image.height, args.conf, args.min_box_size, args.max_area_ratio),
            args.nms,
            args.max_predictions,
        )
        gt_boxes = np.array(
            [xywh_to_xyxy(annotation["bbox"]) for annotation in annotations_by_image.get(image_id, [])],
            dtype=np.float32,
        ).reshape((-1, 4))
        best_iou = max((float(box_iou(detection.box, gt_boxes).max(initial=0.0)) for detection in detections), default=0.0)
        if best_iou >= 0.3:
            hit_iou_03 += 1
        row = {
            "image_id": image_id,
            "file_name": image_meta["file_name"],
            "gt_boxes": len(gt_boxes),
            "detections": len(detections),
            "top_score": max((detection.score for detection in detections), default=0.0),
            "best_iou": best_iou,
        }
        rows.append(row)
        if saved < args.sample_images and (len(gt_boxes) > 0 or detections):
            draw_model_overlay(image, gt_boxes, detections, args.output_dir / "samples" / str(image_meta["file_name"]))
            if args.phone_image_dir:
                draw_phone_overlay(
                    args.phone_image_dir / str(image_meta["file_name"]),
                    annotations_by_image.get(image_id, []),
                    args.output_dir / "phone_samples" / str(image_meta["file_name"]),
                )
            saved += 1

    positive_images = sum(1 for row in rows if row["gt_boxes"] > 0)
    summary = {
        "model": str(args.model),
        "ann_file": str(args.ann_file),
        "image_dir": str(args.image_dir),
        "num_images": len(rows),
        "positive_images": positive_images,
        "negative_images": len(rows) - positive_images,
        "images_with_iou_ge_0_3": hit_iou_03,
        "mean_detections": float(np.mean([row["detections"] for row in rows])) if rows else 0.0,
        "mean_best_iou_positive": float(np.mean([row["best_iou"] for row in rows if row["gt_boxes"] > 0])) if positive_images else 0.0,
        "rows": rows,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
