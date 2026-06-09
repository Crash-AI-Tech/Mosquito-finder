#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import coremltools as ct
import numpy as np
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "data" / "external" / "mosquito_alert_tigapics" / "images"
DEFAULT_MODEL = REPO_ROOT / "Mosquito-finder" / "DfineMosquitoDetector.mlpackage"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "mosquito_alert_pseudolabel_dfine"
DEFAULT_REPORT_DIR = REPO_ROOT / "artifacts" / "mosquito_alert_pseudolabel_dfine"
CODE_PROJECT_ROOT = REPO_ROOT.parents[1]
YOLOX_ROOT = CODE_PROJECT_ROOT / "ml-frameworks" / "YOLOX"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}


@dataclass(frozen=True)
class Candidate:
    score: float
    box_xyxy: np.ndarray

    @property
    def width(self) -> float:
        return float(max(0.0, self.box_xyxy[2] - self.box_xyxy[0]))

    @property
    def height(self) -> float:
        return float(max(0.0, self.box_xyxy[3] - self.box_xyxy[1]))

    @property
    def area(self) -> float:
        return self.width * self.height

    def as_coco_bbox(self) -> list[float]:
        return [
            round(float(self.box_xyxy[0]), 3),
            round(float(self.box_xyxy[1]), 3),
            round(self.width, 3),
            round(self.height, 3),
        ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pseudo-label Mosquito Alert Tigapics with a high-precision CoreML detector."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--image-size", type=int, default=416)
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--nms", type=float, default=0.45)
    parser.add_argument("--max-boxes", type=int, default=3)
    parser.add_argument("--min-box-size", type=float, default=6.0)
    parser.add_argument("--max-area-ratio", type=float, default=0.30)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument("--review-limit", type=int, default=80)
    parser.add_argument("--copy-images", action="store_true")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--yolox-checkpoint", type=Path, default=None)
    parser.add_argument("--yolox-exp-module", default="training.yolox_kaggle_smoke")
    parser.add_argument("--yolox-device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--yolox-conf", type=float, default=0.35)
    parser.add_argument("--agreement-iou", type=float, default=0.20)
    parser.add_argument(
        "--require-yolox-agreement",
        action="store_true",
        help="Keep a D-FINE pseudo box only when a YOLOX box overlaps it.",
    )
    return parser


def iter_images(source_dir: Path) -> list[Path]:
    return sorted(
        path for path in source_dir.rglob("*")
        if path.is_file() and path.suffix in IMAGE_EXTENSIONS
    )


def split_for_path(path: Path, source_dir: Path, val_ratio: float) -> str:
    rel = path.relative_to(source_dir).as_posix()
    bucket = int(hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val2017" if bucket < val_ratio else "train2017"


def unique_output_name(path: Path, source_dir: Path) -> str:
    rel = path.relative_to(source_dir).as_posix()
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
    return f"{path.parent.name}_{path.stem}_{digest}{path.suffix.lower()}"


def link_or_copy(source: Path, target: Path, copy_images: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()
    if copy_images:
        shutil.copy2(source, target)
    else:
        target.symlink_to(source.resolve())


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


def nms(candidates: list[Candidate], iou_threshold: float, max_boxes: int) -> list[Candidate]:
    selected: list[Candidate] = []
    remaining = sorted(candidates, key=lambda item: item.score, reverse=True)

    while remaining and len(selected) < max_boxes:
        current = remaining.pop(0)
        selected.append(current)
        if not remaining:
            break
        remaining_boxes = np.vstack([item.box_xyxy for item in remaining]).astype(np.float32)
        keep = box_iou(current.box_xyxy, remaining_boxes) < iou_threshold
        remaining = [item for item, should_keep in zip(remaining, keep) if bool(should_keep)]

    return selected


class YoloXAgreementDetector:
    def __init__(self, checkpoint_path: Path, exp_module: str, requested_device: str) -> None:
        if str(YOLOX_ROOT) not in sys.path:
            sys.path.insert(0, str(YOLOX_ROOT))
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        import torch
        from yolox.data.data_augment import ValTransform
        from yolox.utils import postprocess

        self.torch = torch
        self.postprocess = postprocess
        self.transform = ValTransform(legacy=False)
        self.device = self._choose_device(requested_device)
        self.exp = importlib.import_module(exp_module).Exp()
        self.model = self.exp.get_model().to(self.device)
        checkpoint = torch.load(checkpoint_path, map_location="cpu")
        self.model.load_state_dict(checkpoint["model"] if "model" in checkpoint else checkpoint)
        self.model.eval()

    def _choose_device(self, requested: str):
        if requested == "auto":
            if self.torch.backends.mps.is_available():
                return self.torch.device("mps")
            return self.torch.device("cpu")
        return self.torch.device(requested)

    def predict(self, image: Image.Image, confidence: float, nms_threshold: float) -> list[Candidate]:
        rgb = image.convert("RGB")
        image_array = np.asarray(rgb)[:, :, ::-1].copy()
        tensor, _ = self.transform(image_array, None, self.exp.test_size)
        tensor = self.torch.from_numpy(tensor).unsqueeze(0).float().to(self.device)

        with self.torch.no_grad():
            outputs = self.model(tensor)
            outputs = self.postprocess(
                outputs,
                self.exp.num_classes,
                confidence,
                nms_threshold,
                class_agnostic=True,
            )

        if outputs[0] is None:
            return []

        ratio = min(self.exp.test_size[0] / rgb.height, self.exp.test_size[1] / rgb.width)
        output = outputs[0].detach().cpu().numpy()
        boxes = output[:, :4] / ratio
        scores = output[:, 4] * output[:, 5]

        candidates: list[Candidate] = []
        for box, score in zip(boxes, scores):
            x1, y1, x2, y2 = [float(value) for value in box]
            clipped = np.array(
                [
                    max(0.0, min(float(rgb.width), x1)),
                    max(0.0, min(float(rgb.height), y1)),
                    max(0.0, min(float(rgb.width), x2)),
                    max(0.0, min(float(rgb.height), y2)),
                ],
                dtype=np.float32,
            )
            candidate = Candidate(score=float(score), box_xyxy=clipped)
            if candidate.width > 0 and candidate.height > 0:
                candidates.append(candidate)
        return candidates


def filter_by_yolox_agreement(
    dfine_candidates: list[Candidate],
    yolox_candidates: list[Candidate],
    agreement_iou: float,
) -> tuple[list[Candidate], list[float]]:
    agreed: list[Candidate] = []
    best_ious: list[float] = []
    yolox_boxes = np.vstack([candidate.box_xyxy for candidate in yolox_candidates]).astype(np.float32) \
        if yolox_candidates else np.zeros((0, 4), dtype=np.float32)
    for candidate in dfine_candidates:
        ious = box_iou(candidate.box_xyxy, yolox_boxes)
        best_iou = float(ious.max()) if ious.size else 0.0
        if best_iou >= agreement_iou:
            agreed.append(candidate)
            best_ious.append(best_iou)
    return agreed, best_ious


def parse_dfine_outputs(
    outputs: dict[str, Any],
    image_width: int,
    image_height: int,
    threshold: float,
    min_box_size: float,
    max_area_ratio: float,
) -> list[Candidate]:
    score_output = next(value for key, value in outputs.items() if "score" in key.lower())
    box_output = next(value for key, value in outputs.items() if "box" in key.lower())
    scores = np.asarray(score_output, dtype=np.float32).reshape(-1)
    boxes = np.asarray(box_output, dtype=np.float32)
    boxes = boxes.reshape((-1, 4))

    candidates: list[Candidate] = []
    image_area = float(image_width * image_height)
    for score, raw_box in zip(scores, boxes):
        if float(score) < threshold:
            continue
        cx, cy, width, height = [float(value) for value in raw_box]
        x1 = max(0.0, (cx - width / 2.0) * image_width)
        y1 = max(0.0, (cy - height / 2.0) * image_height)
        x2 = min(float(image_width), (cx + width / 2.0) * image_width)
        y2 = min(float(image_height), (cy + height / 2.0) * image_height)
        candidate = Candidate(score=float(score), box_xyxy=np.array([x1, y1, x2, y2], dtype=np.float32))
        if candidate.width < min_box_size or candidate.height < min_box_size:
            continue
        if candidate.area / max(image_area, 1.0) > max_area_ratio:
            continue
        candidates.append(candidate)
    return candidates


def draw_review_image(image: Image.Image, candidates: list[Candidate], output_path: Path) -> None:
    review = image.convert("RGB").copy()
    draw = ImageDraw.Draw(review)
    for candidate in candidates:
        x1, y1, x2, y2 = [float(value) for value in candidate.box_xyxy]
        draw.rectangle((x1, y1, x2, y2), outline=(255, 0, 0), width=3)
        draw.text((x1, max(0, y1 - 14)), f"{candidate.score:.3f}", fill=(255, 0, 0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review.save(output_path, quality=92)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    args.source_dir = args.source_dir.resolve()
    args.model = args.model.resolve()
    args.output_dir = args.output_dir.resolve()
    args.report_dir = args.report_dir.resolve()
    if args.clean:
        if args.output_dir.exists():
            shutil.rmtree(args.output_dir)
        if args.report_dir.exists():
            shutil.rmtree(args.report_dir)

    images = iter_images(args.source_dir)
    if args.max_images > 0:
        images = images[: args.max_images]

    model = ct.models.MLModel(str(args.model))
    yolox_detector = None
    if args.yolox_checkpoint:
        args.yolox_checkpoint = args.yolox_checkpoint.resolve()
        yolox_detector = YoloXAgreementDetector(
            args.yolox_checkpoint,
            args.yolox_exp_module,
            args.yolox_device,
        )
    coco_by_split: dict[str, dict[str, list[dict[str, Any]]]] = {
        "train2017": {"images": [], "annotations": []},
        "val2017": {"images": [], "annotations": []},
    }
    accepted_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    annotation_ids = {"train2017": 1, "val2017": 1}
    image_ids = {"train2017": 1, "val2017": 1}
    review_written = 0
    started = time.perf_counter()

    for index, image_path in enumerate(images, 1):
        try:
            with Image.open(image_path) as opened:
                original = opened.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            rejected_rows.append({"source": str(image_path), "reason": "invalid_image", "detail": str(exc)})
            continue

        model_input = original.resize((args.image_size, args.image_size), Image.Resampling.BILINEAR)
        outputs = model.predict({"images": model_input})
        raw_candidates = parse_dfine_outputs(
            outputs=outputs,
            image_width=original.width,
            image_height=original.height,
            threshold=args.threshold,
            min_box_size=args.min_box_size,
            max_area_ratio=args.max_area_ratio,
        )
        candidates = nms(raw_candidates, args.nms, args.max_boxes)
        yolox_candidates: list[Candidate] = []
        agreement_ious: list[float] = []
        if yolox_detector is not None and candidates:
            yolox_candidates = yolox_detector.predict(original, args.yolox_conf, args.nms)
            if args.require_yolox_agreement:
                candidates, agreement_ious = filter_by_yolox_agreement(
                    candidates,
                    yolox_candidates,
                    args.agreement_iou,
                )

        if not candidates:
            best_score = 0.0
            score_output = next(value for key, value in outputs.items() if "score" in key.lower())
            if np.asarray(score_output).size:
                best_score = float(np.asarray(score_output, dtype=np.float32).max())
            rejected_rows.append(
                {
                    "source": str(image_path.relative_to(args.source_dir)),
                    "reason": "no_yolox_agreement"
                    if args.require_yolox_agreement and yolox_detector is not None and raw_candidates
                    else "no_candidate_above_threshold",
                    "best_score": best_score,
                    "yolox_candidates": len(yolox_candidates),
                }
            )
            continue

        split = split_for_path(image_path, args.source_dir, args.val_ratio)
        output_name = unique_output_name(image_path, args.source_dir)
        output_image = args.output_dir / split / output_name
        link_or_copy(image_path, output_image, args.copy_images)

        image_id = image_ids[split]
        image_ids[split] += 1
        coco_by_split[split]["images"].append(
            {
                "id": image_id,
                "file_name": output_name,
                "width": original.width,
                "height": original.height,
                "source_file": image_path.relative_to(args.source_dir).as_posix(),
                "pseudo_label_model": args.model.name,
            }
        )

        for candidate in candidates:
            bbox = candidate.as_coco_bbox()
            coco_by_split[split]["annotations"].append(
                {
                    "id": annotation_ids[split],
                    "image_id": image_id,
                    "category_id": 0,
                    "bbox": bbox,
                    "area": round(bbox[2] * bbox[3], 3),
                    "iscrowd": 0,
                    "score": round(candidate.score, 6),
                    "pseudo": True,
                }
            )
            annotation_ids[split] += 1

        accepted_rows.append(
            {
                "source": image_path.relative_to(args.source_dir).as_posix(),
                "split": split,
                "output_image": output_image.relative_to(REPO_ROOT).as_posix(),
                "boxes": len(candidates),
                "best_score": max(candidate.score for candidate in candidates),
                "yolox_candidates": len(yolox_candidates),
                "best_agreement_iou": max(agreement_ious) if agreement_ious else None,
            }
        )

        if review_written < args.review_limit:
            review_path = args.report_dir / "review" / split / output_name
            draw_review_image(original, candidates, review_path)
            review_written += 1

        if index % 250 == 0:
            elapsed = time.perf_counter() - started
            print(
                f"processed={index} accepted={len(accepted_rows)} rejected={len(rejected_rows)} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )

    for split, payload in coco_by_split.items():
        payload["categories"] = [{"id": 0, "name": "mosquito", "supercategory": "insect"}]
        write_json(args.output_dir / "annotations" / f"instances_{split}.json", payload)

    split_summary = {
        split: {
            "images": len(payload["images"]),
            "boxes": len(payload["annotations"]),
        }
        for split, payload in coco_by_split.items()
    }
    summary = {
        "source_dir": str(args.source_dir),
        "model": str(args.model),
        "output_dir": str(args.output_dir),
        "format": "coco",
        "class_name": "mosquito",
        "threshold": args.threshold,
        "nms": args.nms,
        "max_boxes": args.max_boxes,
        "min_box_size": args.min_box_size,
        "max_area_ratio": args.max_area_ratio,
        "yolox_checkpoint": str(args.yolox_checkpoint) if args.yolox_checkpoint else None,
        "require_yolox_agreement": args.require_yolox_agreement,
        "yolox_conf": args.yolox_conf if args.yolox_checkpoint else None,
        "agreement_iou": args.agreement_iou if args.yolox_checkpoint else None,
        "input_images": len(images),
        "accepted_images": len(accepted_rows),
        "rejected_images": len(rejected_rows),
        "splits": split_summary,
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(args.output_dir / "summary.json", summary)
    write_json(args.report_dir / "accepted_manifest.json", {"samples": accepted_rows})
    write_json(args.report_dir / "rejected_manifest.json", {"samples": rejected_rows})
    write_json(args.report_dir / "summary.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
