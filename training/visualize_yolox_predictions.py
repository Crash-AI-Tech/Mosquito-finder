#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
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

from training.yolox_kaggle_smoke import Exp  # noqa: E402
from yolox.data.data_augment import ValTransform  # noqa: E402
from yolox.utils import postprocess  # noqa: E402


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(requested)


def xywh_to_xyxy(box: list[float]) -> np.ndarray:
    x, y, w, h = box
    return np.array([x, y, x + w, y + h], dtype=np.float32)


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


def draw_box(
    image: np.ndarray,
    box: np.ndarray,
    color: tuple[int, int, int],
    label: str,
) -> None:
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        image,
        label,
        (x1, max(20, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Visualize YOLOX mosquito predictions against COCO validation boxes."
    )
    parser.add_argument("--checkpoint", required=True)
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
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--num-images", type=int, default=12)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--nms", type=float, default=0.45)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = Path(args.image_dir)
    ann_data = json.loads(Path(args.ann_file).read_text(encoding="utf-8"))

    annotations_by_image: dict[int, list[np.ndarray]] = {}
    for ann in ann_data["annotations"]:
        annotations_by_image.setdefault(ann["image_id"], []).append(xywh_to_xyxy(ann["bbox"]))

    images = ann_data["images"][: args.num_images]
    device = choose_device(args.device)
    exp = Exp()
    model = exp.get_model().to(device)
    checkpoint = torch.load(args.checkpoint, map_location="cpu")
    model.load_state_dict(checkpoint["model"])
    model.eval()
    transform = ValTransform(legacy=False)

    rows = []
    with torch.no_grad():
        for image_meta in images:
            image_path = image_dir / image_meta["file_name"]
            image = cv2.imread(str(image_path))
            if image is None:
                raise FileNotFoundError(image_path)
            original = image.copy()
            tensor, _ = transform(image, None, exp.test_size)
            tensor = torch.from_numpy(tensor).unsqueeze(0).float().to(device)
            outputs = model(tensor)
            outputs = postprocess(outputs, exp.num_classes, args.conf, args.nms, class_agnostic=True)

            ratio = min(exp.test_size[0] / image.shape[0], exp.test_size[1] / image.shape[1])
            pred_boxes = np.zeros((0, 4), dtype=np.float32)
            pred_scores = np.zeros((0,), dtype=np.float32)
            if outputs[0] is not None:
                output = outputs[0].detach().cpu().numpy()
                pred_boxes = output[:, :4] / ratio
                pred_scores = output[:, 4] * output[:, 5]

            gt_boxes = np.array(annotations_by_image.get(image_meta["id"], []), dtype=np.float32)
            best_iou = 0.0
            top_score = 0.0
            if pred_boxes.size:
                top_idx = int(np.argmax(pred_scores))
                top_score = float(pred_scores[top_idx])
                ious = box_iou(pred_boxes[top_idx], gt_boxes)
                best_iou = float(ious.max()) if ious.size else 0.0

            for gt_box in gt_boxes:
                draw_box(original, gt_box, (0, 180, 0), "gt")
            for box, score in zip(pred_boxes[:5], pred_scores[:5]):
                draw_box(original, box, (0, 0, 255), f"pred {score:.2f}")

            output_path = output_dir / image_meta["file_name"]
            cv2.imwrite(str(output_path), original)
            rows.append(
                {
                    "file_name": image_meta["file_name"],
                    "predictions": int(len(pred_boxes)),
                    "top_score": top_score,
                    "best_iou": best_iou,
                    "output": str(output_path),
                }
            )

    summary = {
        "checkpoint": args.checkpoint,
        "device": str(device),
        "num_images": len(rows),
        "conf": args.conf,
        "nms": args.nms,
        "mean_best_iou": float(np.mean([row["best_iou"] for row in rows])) if rows else 0.0,
        "mean_top_score": float(np.mean([row["top_score"] for row in rows])) if rows else 0.0,
        "images_with_predictions": sum(1 for row in rows if row["predictions"] > 0),
        "rows": rows,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
