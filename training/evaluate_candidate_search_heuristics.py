#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Candidate:
    box: np.ndarray
    score: float
    source: str

    @property
    def center(self) -> tuple[float, float]:
        return float((self.box[0] + self.box[2]) / 2.0), float((self.box[1] + self.box[3]) / 2.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate Stage-1 traditional candidate search on COCO phone-frame validation data."
    )
    parser.add_argument("--ann-file", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--num-images", type=int, default=0)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--step", type=int, default=18)
    parser.add_argument("--margin", type=int, default=36)
    parser.add_argument("--local-contrast-threshold", type=float, default=0.06)
    parser.add_argument("--background-variance-threshold", type=float, default=0.018)
    parser.add_argument("--hit-center-multiplier", type=float, default=1.8)
    parser.add_argument("--hit-min-padding", type=float, default=16.0)
    parser.add_argument("--sample-limit", type=int, default=36)
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


def nms(candidates: list[Candidate], iou_threshold: float) -> list[Candidate]:
    selected: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if not selected:
            selected.append(candidate)
            continue
        boxes = np.vstack([item.box for item in selected]).astype(np.float32)
        if float(box_iou(candidate.box, boxes).max(initial=0.0)) < iou_threshold:
            selected.append(candidate)
    return selected


def sample_patch(gray: np.ndarray, center_x: int, center_y: int, radius: int, stride: int | None = None) -> np.ndarray:
    height, width = gray.shape
    stride = stride or max(1, radius // 2)
    values: list[float] = []
    for y in range(center_y - radius, center_y + radius + 1, stride):
        if y < 0 or y >= height:
            continue
        for x in range(center_x - radius, center_x + radius + 1, stride):
            if 0 <= x < width:
                values.append(float(gray[y, x]))
    return np.asarray(values, dtype=np.float32)


def sample_ring(gray: np.ndarray, center_x: int, center_y: int, inner_radius: int, outer_radius: int) -> np.ndarray:
    height, width = gray.shape
    values: list[float] = []
    for dy in range(-outer_radius, outer_radius + 1, 6):
        y = center_y + dy
        if y < 0 or y >= height:
            continue
        for dx in range(-outer_radius, outer_radius + 1, 6):
            distance = math.sqrt(float(dx * dx + dy * dy))
            if distance < inner_radius or distance > outer_radius:
                continue
            x = center_x + dx
            if 0 <= x < width:
                values.append(float(gray[y, x]))
    return np.asarray(values, dtype=np.float32)


def make_candidate(x: int, y: int, size: float, score: float, source: str, width: int, height: int) -> Candidate:
    half = size / 2.0
    box = np.array(
        [
            max(0.0, x - half),
            max(0.0, y - half),
            min(float(width), x + half),
            min(float(height), y + half),
        ],
        dtype=np.float32,
    )
    return Candidate(box=box, score=float(max(0.0, min(1.0, score))), source=source)


def spatially_diverse(candidates: list[Candidate], width: int, height: int, max_candidates: int) -> list[Candidate]:
    if len(candidates) <= max_candidates:
        return candidates
    selected: list[Candidate] = []
    selected_ids: set[int] = set()
    occupied: set[tuple[int, int]] = set()
    for index, candidate in enumerate(candidates):
        cx, cy = candidate.center
        column = min(2, max(0, int(cx / max(1.0, width / 3.0))))
        row = min(3, max(0, int(cy / max(1.0, height / 4.0))))
        key = (column, row)
        if key not in occupied:
            selected.append(candidate)
            selected_ids.add(index)
            occupied.add(key)
        if len(selected) >= max_candidates:
            break
    if len(selected) < max_candidates:
        for index, candidate in enumerate(candidates):
            if index not in selected_ids:
                selected.append(candidate)
            if len(selected) >= max_candidates:
                break
    return selected + [candidate for index, candidate in enumerate(candidates) if index not in selected_ids]


def find_connected_dark_components(
    gray: np.ndarray,
    frame_mean: float,
    local_contrast_threshold: float,
    background_variance_threshold: float,
) -> list[Candidate]:
    height, width = gray.shape
    cell_size = 12
    grid_width = max(1, width // cell_size)
    grid_height = max(1, height // cell_size)
    margin_cells = max(2, 36 // cell_size)
    mask = np.zeros((grid_height, grid_width), dtype=np.uint8)
    contrast = np.zeros((grid_height, grid_width), dtype=np.float32)

    for gy in range(margin_cells, max(margin_cells, grid_height - margin_cells)):
        for gx in range(margin_cells, max(margin_cells, grid_width - margin_cells)):
            x = gx * cell_size + cell_size // 2
            y = gy * cell_size + cell_size // 2
            center = sample_patch(gray, x, y, radius=2)
            ring = sample_ring(gray, x, y, inner_radius=10, outer_radius=20)
            if not len(center) or not len(ring):
                continue
            local_contrast = float(ring.mean() - center.mean())
            dark_enough = float(center.mean()) < max(0.62, frame_mean + 0.08)
            compact_signal = local_contrast > max(0.018, local_contrast_threshold * 0.48)
            texture_ok = float(ring.var()) < max(0.035, background_variance_threshold * 14.0)
            if dark_enough and compact_signal and texture_ok:
                mask[gy, gx] = 1
                contrast[gy, gx] = local_contrast

    visited = np.zeros_like(mask, dtype=np.uint8)
    components: list[Candidate] = []
    for start_y in range(margin_cells, max(margin_cells, grid_height - margin_cells)):
        for start_x in range(margin_cells, max(margin_cells, grid_width - margin_cells)):
            if visited[start_y, start_x] or not mask[start_y, start_x]:
                continue
            stack = [(start_x, start_y)]
            visited[start_y, start_x] = 1
            cells: list[tuple[int, int]] = []
            contrast_sum = 0.0
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                contrast_sum += float(contrast[cy, cx])
                for ny in range(max(margin_cells, cy - 1), min(grid_height - margin_cells - 1, cy + 1) + 1):
                    for nx in range(max(margin_cells, cx - 1), min(grid_width - margin_cells - 1, cx + 1) + 1):
                        if not visited[ny, nx] and mask[ny, nx]:
                            visited[ny, nx] = 1
                            stack.append((nx, ny))

            if not cells or len(cells) > 26:
                continue
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            component_width = (max(xs) - min(xs) + 1) * cell_size
            component_height = (max(ys) - min(ys) + 1) * cell_size
            max_side = max(component_width, component_height)
            if max_side > 96:
                continue
            center_x = (min(xs) + max(xs) + 1) * cell_size / 2.0
            center_y = (min(ys) + max(ys) + 1) * cell_size / 2.0
            avg_contrast = contrast_sum / max(1, len(cells))
            compactness = min(1.0, len(cells) / 8.0)
            score = min(1.0, avg_contrast * 3.4 + compactness * 0.18) * 0.66
            components.append(make_candidate(int(center_x), int(center_y), max(max_side + 18, 24), score, "component", width, height))
    return components


def find_candidates(
    image_bgr: np.ndarray,
    step: int,
    margin: int,
    local_contrast_threshold: float,
    background_variance_threshold: float,
    max_candidates: int,
) -> list[Candidate]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    height, width = gray.shape
    candidates: list[Candidate] = []
    frame_mean = float(gray.mean())

    for y in range(margin, height - margin, step):
        for x in range(margin, width - margin, step):
            inner = sample_patch(gray, x, y, radius=3)
            middle = sample_patch(gray, x, y, radius=9)
            outer = sample_ring(gray, x, y, inner_radius=12, outer_radius=22)
            if not len(inner) or not len(middle) or not len(outer):
                continue

            inner_mean = float(inner.mean())
            middle_mean = float(middle.mean())
            outer_mean = float(outer.mean())
            outer_variance = float(outer.var())
            middle_variance = float(middle.var())
            dark_contrast = outer_mean - inner_mean
            blob_contrast = middle_mean - inner_mean
            texture_penalty = min(1.0, outer_variance / max(0.0001, background_variance_threshold * 6.0))
            smoothness = 1.0 - texture_penalty

            if dark_contrast > local_contrast_threshold:
                score = min(1.0, dark_contrast * 3.1 + smoothness * 0.22)
                candidates.append(make_candidate(x, y, 22.0, score * 0.78, "dark_spot", width, height))

            if blob_contrast > local_contrast_threshold * 0.78 and outer_variance < background_variance_threshold * 10.0:
                score = min(1.0, blob_contrast * 2.7 + smoothness * 0.18)
                candidates.append(make_candidate(x, y, 28.0, score * 0.74, "blob", width, height))

            local_contrast = math.sqrt(max(0.0, middle_variance))
            if local_contrast > local_contrast_threshold * 0.68 and dark_contrast > local_contrast_threshold * 0.42:
                score = min(1.0, local_contrast * 2.2 + dark_contrast * 1.5)
                candidates.append(make_candidate(x, y, 32.0, score * 0.70, "local_contrast", width, height))

    candidates.extend(find_connected_dark_components(gray, frame_mean, local_contrast_threshold, background_variance_threshold))
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    return nms(spatially_diverse(ranked, width, height, max_candidates), 0.22)[: max_candidates * 3]


def candidate_hits_gt(
    candidate: Candidate,
    gt_boxes: np.ndarray,
    center_multiplier: float,
    min_padding: float,
) -> bool:
    if gt_boxes.size == 0:
        return False
    if float(box_iou(candidate.box, gt_boxes).max(initial=0.0)) >= 0.03:
        return True
    cx, cy = candidate.center
    for gt in gt_boxes:
        gt_width = float(gt[2] - gt[0])
        gt_height = float(gt[3] - gt[1])
        padding = max(min_padding, max(gt_width, gt_height) * center_multiplier)
        if gt[0] - padding <= cx <= gt[2] + padding and gt[1] - padding <= cy <= gt[3] + padding:
            return True
    return False


def evaluate_image(
    candidates: list[Candidate],
    gt_boxes: np.ndarray,
    center_multiplier: float,
    min_padding: float,
) -> dict[str, Any]:
    selected = candidates[:]
    hits = [candidate_hits_gt(candidate, gt_boxes, center_multiplier, min_padding) for candidate in selected]
    positive = len(gt_boxes) > 0
    return {
        "positive": positive,
        "candidate_count": len(selected),
        "hit": bool(any(hits)) if positive else False,
        "false_candidate_count": int(sum(1 for hit in hits if not hit)),
        "best_iou": float(max((box_iou(candidate.box, gt_boxes).max(initial=0.0) for candidate in selected), default=0.0)),
        "top_score": float(selected[0].score) if selected else 0.0,
        "top_source": selected[0].source if selected else "none",
    }


def draw_overlay(image: np.ndarray, gt_boxes: np.ndarray, candidates: list[Candidate], output_path: Path) -> None:
    canvas = image.copy()
    for gt in gt_boxes:
        x1, y1, x2, y2 = [int(round(value)) for value in gt]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 190, 0), 2)
        cv2.putText(canvas, "gt", (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 190, 0), 1, cv2.LINE_AA)
    colors = {
        "dark_spot": (0, 165, 255),
        "blob": (255, 120, 0),
        "local_contrast": (255, 0, 180),
    }
    for index, candidate in enumerate(candidates[:8], start=1):
        color = colors.get(candidate.source, (0, 0, 255))
        x1, y1, x2, y2 = [int(round(value)) for value in candidate.box]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 1)
        cv2.putText(
            canvas,
            f"{index}:{candidate.source[:2]} {candidate.score:.2f}",
            (x1, min(canvas.shape[0] - 6, y2 + 14)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            color,
            1,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    return {
        "images": len(rows),
        "positive_images": len(positives),
        "negative_images": len(negatives),
        "positive_hit_rate": sum(1 for row in positives if row["hit"]) / max(1, len(positives)),
        "mean_candidates": float(np.mean([row["candidate_count"] for row in rows])) if rows else 0.0,
        "mean_false_candidates_on_negative": float(np.mean([row["candidate_count"] for row in negatives])) if negatives else 0.0,
        "mean_best_iou_positive": float(np.mean([row["best_iou"] for row in positives])) if positives else 0.0,
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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = args.output_dir / "samples"
    rows: list[dict[str, Any]] = []
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_negative_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missed_positive_samples = 0
    hit_positive_samples = 0
    negative_samples = 0

    for image_meta in images:
        image_id = int(image_meta["id"])
        image_path = args.image_dir / str(image_meta["file_name"])
        image = cv2.imread(str(image_path))
        if image is None:
            raise FileNotFoundError(image_path)
        candidates = find_candidates(
            image,
            step=args.step,
            margin=args.margin,
            local_contrast_threshold=args.local_contrast_threshold,
            background_variance_threshold=args.background_variance_threshold,
            max_candidates=args.max_candidates,
        )[: args.max_candidates]
        gt_boxes = gt_by_image.get(image_id, np.zeros((0, 4), dtype=np.float32))
        row = {
            "image_id": image_id,
            "file_name": image_meta["file_name"],
            "scenario": image_meta.get("scenario", "unknown"),
            "hard_negative_type": image_meta.get("hard_negative_type", "none"),
            **evaluate_image(candidates, gt_boxes, args.hit_center_multiplier, args.hit_min_padding),
        }
        rows.append(row)
        by_scenario[str(row["scenario"])].append(row)
        by_negative_type[str(row["hard_negative_type"])].append(row)

        should_save = False
        prefix = "other"
        if row["positive"] and not row["hit"] and missed_positive_samples < args.sample_limit // 3:
            missed_positive_samples += 1
            should_save = True
            prefix = "miss_positive"
        elif row["positive"] and row["hit"] and hit_positive_samples < args.sample_limit // 3:
            hit_positive_samples += 1
            should_save = True
            prefix = "hit_positive"
        elif not row["positive"] and row["candidate_count"] > 0 and negative_samples < args.sample_limit // 3:
            negative_samples += 1
            should_save = True
            prefix = "negative_candidates"
        if should_save:
            draw_overlay(image, gt_boxes, candidates, sample_dir / f"{prefix}_{image_meta['file_name']}")

    positives = [row for row in rows if row["positive"]]
    negatives = [row for row in rows if not row["positive"]]
    summary = {
        "ann_file": str(args.ann_file),
        "image_dir": str(args.image_dir),
        "num_images": len(rows),
        "positive_images": len(positives),
        "negative_images": len(negatives),
        "candidate_search_settings": {
            "max_candidates": args.max_candidates,
            "step": args.step,
            "margin": args.margin,
            "local_contrast_threshold": args.local_contrast_threshold,
            "background_variance_threshold": args.background_variance_threshold,
            "hit_center_multiplier": args.hit_center_multiplier,
            "hit_min_padding": args.hit_min_padding,
        },
        "overall": summarize_group(rows),
        "by_scenario": {key: summarize_group(value) for key, value in sorted(by_scenario.items())},
        "by_negative_type": {key: summarize_group(value) for key, value in sorted(by_negative_type.items())},
        "source_distribution": dict(
            sorted(
                {
                    source: sum(1 for row in rows if row["top_source"] == source)
                    for source in {row["top_source"] for row in rows}
                }.items()
            )
        ),
        "rows": rows,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
