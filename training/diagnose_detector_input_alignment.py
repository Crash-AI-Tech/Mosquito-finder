#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parent.parent
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
YOLOX_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "YOLOX"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(YOLOX_ROOT) not in sys.path:
    sys.path.insert(0, str(YOLOX_ROOT))


@dataclass
class Detection:
    score: float
    box: np.ndarray
    source: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose detector input scale, bbox size, and YOLOX/D-FINE prediction alignment."
    )
    parser.add_argument("--ann-file", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--phone-image-dir", type=Path)
    parser.add_argument("--num-images", type=int, default=240)
    parser.add_argument("--sample-images", type=int, default=48)
    parser.add_argument("--yolox-checkpoint", type=Path)
    parser.add_argument("--yolox-exp-module", default="training.yolox_tiny_candidate_v2")
    parser.add_argument("--yolox-device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--yolox-conf", type=float, default=0.01)
    parser.add_argument("--yolox-nms", type=float, default=0.45)
    parser.add_argument("--dfine-model", type=Path)
    parser.add_argument("--dfine-conf", type=float, default=0.01)
    parser.add_argument("--dfine-nms", type=float, default=0.42)
    parser.add_argument("--max-predictions", type=int, default=8)
    return parser


def choose_torch_device(requested: str):
    import torch

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
    box_area = max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))
    areas = np.maximum(0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0, boxes[:, 3] - boxes[:, 1])
    return inter / np.maximum(box_area + areas - inter, 1e-6)


def nms(detections: list[Detection], iou_threshold: float, max_predictions: int) -> list[Detection]:
    selected: list[Detection] = []
    for detection in sorted(detections, key=lambda item: item.score, reverse=True):
        if not selected:
            selected.append(detection)
        else:
            selected_boxes = np.vstack([item.box for item in selected]).astype(np.float32)
            if float(box_iou(detection.box, selected_boxes).max(initial=0.0)) < iou_threshold:
                selected.append(detection)
        if len(selected) >= max_predictions:
            break
    return selected


def load_yolox(checkpoint_path: Path, exp_module: str, requested_device: str):
    import torch
    from yolox.data.data_augment import ValTransform
    from yolox.utils import postprocess

    device = choose_torch_device(requested_device)
    exp = importlib.import_module(exp_module).Exp()
    model = exp.get_model().to(device)
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    model.load_state_dict(checkpoint["model"] if "model" in checkpoint else checkpoint)
    model.eval()
    return {
        "device": device,
        "exp": exp,
        "model": model,
        "transform": ValTransform(legacy=False),
        "postprocess": postprocess,
        "torch": torch,
    }


def predict_yolox(yolox_ctx: dict[str, Any], image_bgr: np.ndarray, conf: float, nms_threshold: float) -> list[Detection]:
    torch = yolox_ctx["torch"]
    exp = yolox_ctx["exp"]
    transform = yolox_ctx["transform"]
    postprocess = yolox_ctx["postprocess"]
    tensor, _ = transform(image_bgr, None, exp.test_size)
    tensor = torch.from_numpy(tensor).unsqueeze(0).float().to(yolox_ctx["device"])
    with torch.no_grad():
        outputs = yolox_ctx["model"](tensor)
        outputs = postprocess(outputs, exp.num_classes, conf, nms_threshold, class_agnostic=True)
    if outputs[0] is None:
        return []
    ratio = min(exp.test_size[0] / image_bgr.shape[0], exp.test_size[1] / image_bgr.shape[1])
    output = outputs[0].detach().cpu().numpy()
    boxes = output[:, :4] / ratio
    scores = output[:, 4] * output[:, 5]
    return [Detection(score=float(score), box=box.astype(np.float32), source="yolox") for box, score in zip(boxes, scores)]


def load_dfine(model_path: Path):
    import coremltools as ct

    return ct.models.MLModel(str(model_path))


def predict_dfine(
    model: Any,
    image_rgb: Image.Image,
    conf: float,
    nms_threshold: float,
    max_predictions: int,
) -> list[Detection]:
    model_input = image_rgb.resize((416, 416), Image.Resampling.BILINEAR)
    outputs = model.predict({"images": model_input})
    score_output = next(value for key, value in outputs.items() if "score" in key.lower())
    box_output = next(value for key, value in outputs.items() if "box" in key.lower())
    scores = np.asarray(score_output, dtype=np.float32).reshape(-1)
    boxes = np.asarray(box_output, dtype=np.float32).reshape((-1, 4))
    detections: list[Detection] = []
    image_width, image_height = image_rgb.size
    image_area = float(image_width * image_height)
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
        if box_width < 2.0 or box_height < 2.0:
            continue
        if box_width * box_height / max(image_area, 1.0) > 0.30:
            continue
        detections.append(Detection(score=float(score), box=np.array([x1, y1, x2, y2], dtype=np.float32), source="dfine"))
    return nms(detections, nms_threshold, max_predictions)


def draw_box(image: np.ndarray, box: np.ndarray, color: tuple[int, int, int], label: str, thickness: int = 2) -> None:
    x1, y1, x2, y2 = [int(round(value)) for value in box]
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
    cv2.putText(image, label, (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)


def draw_sample(
    image_bgr: np.ndarray,
    gt_boxes: np.ndarray,
    detections: list[Detection],
    output_path: Path,
) -> None:
    canvas = image_bgr.copy()
    for gt in gt_boxes:
        draw_box(canvas, gt, (0, 190, 0), "gt", 2)
    colors = {"yolox": (0, 0, 255), "dfine": (220, 0, 220)}
    for detection in detections:
        draw_box(canvas, detection.box, colors.get(detection.source, (255, 255, 0)), f"{detection.source} {detection.score:.2f}", 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)


def draw_phone_sample(
    phone_image_path: Path,
    image_meta: dict[str, Any],
    output_path: Path,
) -> None:
    phone_image = cv2.imread(str(phone_image_path))
    if phone_image is None:
        return
    source_width = float(image_meta.get("source_width", phone_image.shape[1]))
    source_height = float(image_meta.get("source_height", phone_image.shape[0]))
    for ann in image_meta.get("_annotations", []):
        source_box = ann.get("source_phone_box")
        if source_box:
            x, y, width, height = [float(value) for value in source_box]
        else:
            bx, by, bw, bh = ann["bbox"]
            x = bx / 416.0 * source_width
            y = by / 416.0 * source_height
            width = bw / 416.0 * source_width
            height = bh / 416.0 * source_height
        box = np.array([x, y, x + width, y + height], dtype=np.float32)
        draw_box(phone_image, box, (0, 190, 0), "phone gt", 3)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), phone_image)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float32), p))


def bbox_stats(annotations: list[dict[str, Any]], images_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    widths = [float(ann["bbox"][2]) for ann in annotations]
    heights = [float(ann["bbox"][3]) for ann in annotations]
    areas = [w * h for w, h in zip(widths, heights)]
    min_sides = [min(w, h) for w, h in zip(widths, heights)]
    max_sides = [max(w, h) for w, h in zip(widths, heights)]
    aspect = [w / max(h, 1e-6) for w, h in zip(widths, heights)]
    source_aspect = []
    squeeze_aspect_ratio = []
    for ann in annotations:
        image_meta = images_by_id.get(int(ann["image_id"]), {})
        source_box = ann.get("source_phone_box")
        if source_box:
            _, _, sw, sh = [float(value) for value in source_box]
            source_aspect.append(sw / max(sh, 1e-6))
            model_aspect = float(ann["bbox"][2]) / max(float(ann["bbox"][3]), 1e-6)
            squeeze_aspect_ratio.append(model_aspect / max(source_aspect[-1], 1e-6))
        elif "source_width" in image_meta and "source_height" in image_meta:
            source_aspect.append(0.0)
            squeeze_aspect_ratio.append(float(image_meta["source_height"]) / max(float(image_meta["source_width"]), 1e-6))

    return {
        "boxes": len(annotations),
        "width_px": {"p10": percentile(widths, 10), "p50": percentile(widths, 50), "p90": percentile(widths, 90), "min": min(widths, default=0.0), "max": max(widths, default=0.0)},
        "height_px": {"p10": percentile(heights, 10), "p50": percentile(heights, 50), "p90": percentile(heights, 90), "min": min(heights, default=0.0), "max": max(heights, default=0.0)},
        "area_px2": {"p10": percentile(areas, 10), "p50": percentile(areas, 50), "p90": percentile(areas, 90)},
        "min_side_px": {"p10": percentile(min_sides, 10), "p50": percentile(min_sides, 50), "p90": percentile(min_sides, 90)},
        "max_side_px": {"p10": percentile(max_sides, 10), "p50": percentile(max_sides, 50), "p90": percentile(max_sides, 90)},
        "aspect_model": {"p10": percentile(aspect, 10), "p50": percentile(aspect, 50), "p90": percentile(aspect, 90)},
        "aspect_source": {"p10": percentile(source_aspect, 10), "p50": percentile(source_aspect, 50), "p90": percentile(source_aspect, 90)} if source_aspect else None,
        "model_to_source_aspect_multiplier": {
            "p10": percentile(squeeze_aspect_ratio, 10),
            "p50": percentile(squeeze_aspect_ratio, 50),
            "p90": percentile(squeeze_aspect_ratio, 90),
        } if squeeze_aspect_ratio else None,
        "small_box_counts": {
            "min_side_lt_4": sum(1 for value in min_sides if value < 4),
            "min_side_lt_6": sum(1 for value in min_sides if value < 6),
            "min_side_lt_8": sum(1 for value in min_sides if value < 8),
            "min_side_lt_12": sum(1 for value in min_sides if value < 12),
        },
    }


def prediction_summary(detections: list[Detection], gt_boxes: np.ndarray) -> dict[str, Any]:
    by_source: dict[str, list[Detection]] = {}
    for detection in detections:
        by_source.setdefault(detection.source, []).append(detection)
    summary: dict[str, Any] = {}
    for source, source_detections in by_source.items():
        best_iou = 0.0
        top_score = 0.0
        if source_detections:
            top_score = max(detection.score for detection in source_detections)
            if gt_boxes.size:
                best_iou = max(float(box_iou(detection.box, gt_boxes).max(initial=0.0)) for detection in source_detections)
        summary[source] = {
            "detections": len(source_detections),
            "top_score": top_score,
            "best_iou": best_iou,
        }
    return summary


def main() -> int:
    args = build_parser().parse_args()
    ann_data = json.loads(args.ann_file.read_text(encoding="utf-8"))
    images = ann_data["images"][: args.num_images] if args.num_images > 0 else ann_data["images"]
    image_ids = {int(image["id"]) for image in images}
    annotations = [ann for ann in ann_data["annotations"] if int(ann["image_id"]) in image_ids]

    images_by_id = {int(image["id"]): dict(image) for image in images}
    annotations_by_image: dict[int, list[dict[str, Any]]] = {image_id: [] for image_id in image_ids}
    for annotation in annotations:
        annotations_by_image.setdefault(int(annotation["image_id"]), []).append(annotation)
    for image_id, image_annotations in annotations_by_image.items():
        images_by_id[image_id]["_annotations"] = image_annotations

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = args.output_dir / "samples"
    phone_sample_dir = args.output_dir / "phone_samples"

    yolox_ctx = None
    if args.yolox_checkpoint:
        yolox_ctx = load_yolox(args.yolox_checkpoint, args.yolox_exp_module, args.yolox_device)
    dfine_model = load_dfine(args.dfine_model) if args.dfine_model else None

    rows: list[dict[str, Any]] = []
    saved_samples = 0
    with_yolox_hit = 0
    with_dfine_hit = 0

    for image_meta in images:
        image_id = int(image_meta["id"])
        image_path = args.image_dir / str(image_meta["file_name"])
        image_bgr = cv2.imread(str(image_path))
        if image_bgr is None:
            raise FileNotFoundError(image_path)
        gt_boxes = np.array([xywh_to_xyxy(ann["bbox"]) for ann in annotations_by_image.get(image_id, [])], dtype=np.float32).reshape((-1, 4))

        detections: list[Detection] = []
        if yolox_ctx is not None:
            detections.extend(
                nms(
                    predict_yolox(yolox_ctx, image_bgr, args.yolox_conf, args.yolox_nms),
                    args.yolox_nms,
                    args.max_predictions,
                )
            )
        if dfine_model is not None:
            image_rgb = Image.open(image_path).convert("RGB")
            detections.extend(
                predict_dfine(
                    dfine_model,
                    image_rgb,
                    args.dfine_conf,
                    args.dfine_nms,
                    args.max_predictions,
                )
            )

        pred_summary = prediction_summary(detections, gt_boxes)
        if pred_summary.get("yolox", {}).get("best_iou", 0.0) >= 0.3:
            with_yolox_hit += 1
        if pred_summary.get("dfine", {}).get("best_iou", 0.0) >= 0.3:
            with_dfine_hit += 1

        row = {
            "image_id": image_id,
            "file_name": image_meta["file_name"],
            "scenario": image_meta.get("scenario", "unknown"),
            "hard_negative_type": image_meta.get("hard_negative_type", "none"),
            "gt_boxes": len(gt_boxes),
            "prediction_summary": pred_summary,
        }
        rows.append(row)

        should_save = saved_samples < args.sample_images and (len(gt_boxes) > 0 or detections)
        if should_save:
            draw_sample(image_bgr, gt_boxes, detections, sample_dir / str(image_meta["file_name"]))
            if args.phone_image_dir:
                draw_phone_sample(
                    args.phone_image_dir / str(image_meta["file_name"]),
                    images_by_id[image_id],
                    phone_sample_dir / str(image_meta["file_name"]),
                )
            saved_samples += 1

    positive_images = sum(1 for row in rows if row["gt_boxes"] > 0)
    summary = {
        "ann_file": str(args.ann_file),
        "image_dir": str(args.image_dir),
        "phone_image_dir": str(args.phone_image_dir) if args.phone_image_dir else None,
        "num_images": len(images),
        "positive_images": positive_images,
        "negative_images": len(images) - positive_images,
        "bbox_stats": bbox_stats(annotations, images_by_id),
        "models": {
            "yolox_checkpoint": str(args.yolox_checkpoint) if args.yolox_checkpoint else None,
            "yolox_exp_module": args.yolox_exp_module if args.yolox_checkpoint else None,
            "dfine_model": str(args.dfine_model) if args.dfine_model else None,
        },
        "prediction_alignment": {
            "yolox_images_with_iou_ge_0_3": with_yolox_hit,
            "dfine_images_with_iou_ge_0_3": with_dfine_hit,
            "positive_images": positive_images,
        },
        "rows": rows,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
