#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "processed" / "synthetic_phone_detector_coco"
PHONE_SIZE = (1080, 1920)
MODEL_SIZE = 416
CLASS_NAME = "mosquito"
CLASS_ID = 0


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    def clamp(self, width: int, height: int) -> "Box":
        return Box(
            max(0, min(width - 1, self.x1)),
            max(0, min(height - 1, self.y1)),
            max(0, min(width - 1, self.x2)),
            max(0, min(height - 1, self.y2)),
        )

    def to_model_xywh(self, source_width: int, source_height: int) -> list[float]:
        # Stage1Detector currently stretches the camera buffer to 416x416.
        sx = MODEL_SIZE / source_width
        sy = MODEL_SIZE / source_height
        x1 = self.x1 * sx
        y1 = self.y1 * sy
        x2 = self.x2 * sx
        y2 = self.y2 * sy
        return [
            round(x1, 3),
            round(y1, 3),
            round(max(1.0, x2 - x1), 3),
            round(max(1.0, y2 - y1), 3),
        ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate realistic phone-frame mosquito detector data with exact COCO boxes."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-count", type=int, default=9000)
    parser.add_argument("--val-count", type=int, default=1600)
    parser.add_argument("--reality-count", type=int, default=1600)
    parser.add_argument("--positive-ratio", type=float, default=0.48)
    parser.add_argument("--reality-positive-ratio", type=float, default=0.22)
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument("--save-phone-frames", action="store_true")
    parser.add_argument("--clean", action="store_true")
    return parser


def clamp_image(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 0, 255).astype(np.uint8)


def base_surface(rng: random.Random, width: int, height: int) -> tuple[Image.Image, str]:
    surface_type = rng.choices(
        ["paint", "ceiling", "curtain", "wood", "tile", "corner", "fabric", "black_bag", "cabinet_under"],
        weights=[0.20, 0.12, 0.13, 0.10, 0.06, 0.11, 0.13, 0.09, 0.06],
        k=1,
    )[0]
    base = rng.randint(174, 246)
    if surface_type in {"black_bag", "cabinet_under"}:
        base = rng.randint(34, 92)
    elif surface_type == "fabric":
        base = rng.randint(72, 198)
    pixels = np.full((height, width, 3), base, dtype=np.float32)
    pixels += np.random.normal(0, rng.uniform(2.5, 11.0), pixels.shape)

    x_grad = np.linspace(rng.uniform(-26, 18), rng.uniform(-18, 28), width, dtype=np.float32)
    y_grad = np.linspace(rng.uniform(-22, 20), rng.uniform(-20, 26), height, dtype=np.float32)
    pixels += x_grad[None, :, None] + y_grad[:, None, None]

    if surface_type == "curtain":
        for step in (rng.randint(7, 14), rng.randint(18, 36)):
            pixels[:, ::step, :] -= rng.uniform(8, 22)
            pixels[:: max(3, step + rng.randint(-3, 5)), :, :] -= rng.uniform(3, 12)
        pixels[:, :, 0] *= rng.uniform(0.92, 1.08)
        pixels[:, :, 2] *= rng.uniform(0.95, 1.12)
    elif surface_type == "wood":
        tone = rng.randint(88, 158)
        pixels[:, :, 0] = tone + rng.randint(24, 70)
        pixels[:, :, 1] = tone * rng.uniform(0.68, 0.90)
        pixels[:, :, 2] = tone * rng.uniform(0.35, 0.58)
        wave = np.sin(np.linspace(0, rng.uniform(18, 38), width))[None, :, None] * rng.uniform(7, 20)
        pixels += wave
        for x in range(rng.randint(0, 28), width, rng.randint(28, 72)):
            pixels[:, x : min(width, x + rng.randint(4, 14)), :] += rng.uniform(-28, 18)
    elif surface_type == "tile":
        grid = rng.randint(130, 240)
        line = base - rng.randint(18, 44)
        for x in range(rng.randint(0, grid), width, grid):
            pixels[:, max(0, x - 2) : min(width, x + 3), :] = line
        for y in range(rng.randint(0, grid), height, grid):
            pixels[max(0, y - 2) : min(height, y + 3), :, :] = line
    elif surface_type == "corner":
        edge_x = rng.randint(width // 5, width * 4 // 5)
        edge_y = rng.randint(height // 5, height * 4 // 5)
        if rng.random() < 0.8:
            pixels[:, max(0, edge_x - 3) : min(width, edge_x + 3), :] -= rng.uniform(14, 46)
        if rng.random() < 0.55:
            pixels[max(0, edge_y - 3) : min(height, edge_y + 3), :, :] -= rng.uniform(10, 34)
    elif surface_type == "fabric":
        pixels[:, :, rng.randrange(3)] *= rng.uniform(0.70, 1.18)
        stripe_a = rng.randint(6, 18)
        stripe_b = rng.randint(14, 42)
        pixels[:, ::stripe_a, :] += rng.uniform(-24, 18)
        pixels[::stripe_b, :, :] += rng.uniform(-18, 14)
        for _ in range(rng.randint(12, 36)):
            y = rng.randint(0, height - 1)
            pixels[max(0, y - 1) : min(height, y + 2), :, :] += rng.uniform(-12, 10)
    elif surface_type == "black_bag":
        pixels[:, :, 0] *= rng.uniform(0.72, 1.08)
        pixels[:, :, 1] *= rng.uniform(0.72, 1.04)
        pixels[:, :, 2] *= rng.uniform(0.78, 1.18)
        for _ in range(rng.randint(25, 80)):
            x = rng.randint(0, width - 1)
            y = rng.randint(0, height - 1)
            r = rng.randint(2, 18)
            pixels[max(0, y - r) : min(height, y + r), max(0, x - r) : min(width, x + r), :] += rng.uniform(-20, 32)
    elif surface_type == "cabinet_under":
        pixels *= rng.uniform(0.42, 0.78)
        edge_y = rng.randint(height // 8, height // 3)
        pixels[:edge_y, :, :] -= rng.uniform(16, 42)
        pixels[max(0, edge_y - 4) : min(height, edge_y + 6), :, :] += rng.uniform(8, 28)

    image = Image.fromarray(clamp_image(pixels), "RGB")
    return image.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 0.75))), surface_type


def apply_phone_lighting(image: Image.Image, rng: random.Random) -> Image.Image:
    width, height = image.size
    arr = np.asarray(image).astype(np.float32)
    yy, xx = np.mgrid[:height, :width]
    cx = rng.randint(width // 5, width * 4 // 5)
    cy = rng.randint(height // 5, height * 4 // 5)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    radius = rng.uniform(width * 0.25, width * 0.60)
    falloff = np.clip((dist - radius) / rng.uniform(width * 0.65, width * 1.25), 0, 1)
    if rng.random() < 0.65:
        arr *= 1.0 - falloff[:, :, None] * rng.uniform(0.18, 0.52)
        highlight = np.clip(1.0 - dist / rng.uniform(width * 0.55, width * 1.25), 0, 1)
        arr += highlight[:, :, None] * rng.uniform(6, 28)
    else:
        arr *= rng.uniform(0.55, 0.92)
    return Image.fromarray(clamp_image(arr), "RGB")


def draw_artifacts(image: Image.Image, rng: random.Random) -> dict[str, int]:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    counts = {"dust": 0, "scratch": 0, "shadow_patch": 0}
    for _ in range(rng.randint(10, 42)):
        kind = rng.random()
        x = rng.randint(8, width - 8)
        y = rng.randint(8, height - 8)
        shade = rng.randint(18, 150)
        if kind < 0.34:
            r = rng.randint(1, 12)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(shade, shade, shade))
            counts["dust"] += 1
        elif kind < 0.64:
            length = rng.randint(5, 65)
            angle = rng.uniform(0, math.tau)
            draw.line(
                [(x, y), (x + math.cos(angle) * length, y + math.sin(angle) * length)],
                fill=(shade, shade, shade),
                width=rng.randint(1, 3),
            )
            counts["scratch"] += 1
        else:
            r = rng.randint(2, 18)
            points = [(x + rng.randint(-r, r), y + rng.randint(-r, r)) for _ in range(rng.randint(4, 9))]
            draw.polygon(points, fill=(shade, shade, shade))
            counts["shadow_patch"] += 1
    return counts


def draw_near_miss_insects(image: Image.Image, rng: random.Random) -> int:
    draw = ImageDraw.Draw(image)
    width, height = image.size
    count = rng.randint(0, 6)
    for _ in range(count):
        x = rng.randint(32, width - 32)
        y = rng.randint(32, height - 32)
        shade = rng.randint(8, 80)
        body_w = rng.randint(3, 13)
        body_h = rng.randint(3, 18)
        if rng.random() < 0.5:
            draw.ellipse([x - body_w, y - body_h, x + body_w, y + body_h], fill=(shade, shade, shade))
        else:
            draw.rectangle([x - body_w, y - body_h // 2, x + body_w, y + body_h // 2], fill=(shade, shade, shade))
        for _ in range(rng.randint(0, 4)):
            dx = rng.choice([-1, 1]) * rng.randint(7, 24)
            dy = rng.randint(-12, 12)
            draw.line([(x, y), (x + dx, y + dy)], fill=(shade, shade, shade), width=1)
    return count


def draw_mosquito(image: Image.Image, rng: random.Random, wide_search: bool) -> Box:
    width, height = image.size
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if wide_search:
        body_w = rng.randint(3, 10)
        body_h = rng.randint(9, 28)
    else:
        body_w = rng.randint(8, 20)
        body_h = rng.randint(18, 50)
    cx = rng.randint(70, width - 70)
    cy = rng.randint(110, height - 110)
    angle = rng.uniform(-math.pi, math.pi)
    dark = rng.randint(5, 45)

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_dx = rng.choice([-1, 1]) * rng.randint(4, 20)
    shadow_dy = rng.choice([-1, 1]) * rng.randint(4, 20)
    shadow_draw.ellipse(
        [
            cx - body_w + shadow_dx,
            cy - body_h + shadow_dy,
            cx + body_w + shadow_dx,
            cy + body_h + shadow_dy,
        ],
        fill=(0, 0, 0, rng.randint(18, 82)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(rng.uniform(1.6, 5.2)))
    image.paste(shadow, (0, 0), shadow)

    def rot(px: float, py: float) -> tuple[int, int]:
        rx = math.cos(angle) * px - math.sin(angle) * py
        ry = math.sin(angle) * px + math.cos(angle) * py
        return int(cx + rx), int(cy + ry)

    for side in (-1, 1):
        for anchor in (-0.42, -0.1, 0.24):
            start = rot(side * body_w * 0.30, anchor * body_h)
            knee = rot(side * rng.uniform(10, 26), anchor * body_h + rng.uniform(-12, 12))
            end = rot(side * rng.uniform(20, 52), anchor * body_h + rng.uniform(-26, 26))
            draw.line([start, knee, end], fill=(dark, dark, dark, rng.randint(140, 238)), width=1)

    for side in (-1, 1):
        wx, wy = rot(side * body_w * 0.8, -body_h * 0.1)
        draw.ellipse(
            [
                wx - rng.randint(8, 22),
                wy - rng.randint(5, 18),
                wx + rng.randint(8, 22),
                wy + rng.randint(10, 30),
            ],
            fill=(60, 60, 60, rng.randint(18, 72)),
        )

    draw.ellipse([cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 2], fill=(dark, dark, dark, rng.randint(220, 255)))
    hx, hy = rot(0, -body_h * 0.65)
    hr = max(2, body_w // 3)
    draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(dark, dark, dark, 238))
    if rng.random() < 0.42:
        layer = layer.filter(ImageFilter.GaussianBlur(rng.uniform(0.25, 1.1)))
    image.paste(layer, (0, 0), layer)

    alpha = np.asarray(layer.split()[-1])
    ys, xs = np.where(alpha > 10)
    pad = rng.randint(3, 9)
    return Box(float(xs.min() - pad), float(ys.min() - pad), float(xs.max() + pad), float(ys.max() + pad)).clamp(width, height)


def degrade_phone_frame(image: Image.Image, rng: random.Random) -> Image.Image:
    if rng.random() < 0.75:
        image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.78, 1.42))
    if rng.random() < 0.70:
        image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.70, 1.20))
    if rng.random() < 0.65:
        arr = np.asarray(image).astype(np.float32)
        arr += np.random.normal(0, rng.uniform(1.0, 8.0), arr.shape)
        image = Image.fromarray(clamp_image(arr), "RGB")
    if rng.random() < 0.38:
        image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.15, 0.95)))
    if rng.random() < 0.28:
        image = ImageEnhance.Sharpness(image).enhance(rng.uniform(0.55, 1.65))
    return image


def make_phone_frame(rng: random.Random, positive: bool, split: str) -> tuple[Image.Image, list[Box], dict[str, Any]]:
    width, height = PHONE_SIZE
    image, surface_type = base_surface(rng, width, height)
    image = apply_phone_lighting(image, rng)
    artifact_counts = draw_artifacts(image, rng)
    near_miss_count = draw_near_miss_insects(image, rng)
    boxes: list[Box] = []
    if positive:
        for _ in range(1 if rng.random() < 0.90 else 2):
            boxes.append(draw_mosquito(image, rng, wide_search=rng.random() < 0.78 or split == "reality2017"))
    image = degrade_phone_frame(image, rng)
    hard_negative_type = "none"
    if not boxes:
        if near_miss_count:
            hard_negative_type = "near_miss_insect"
        elif surface_type in {"fabric", "black_bag", "wood", "cabinet_under"}:
            hard_negative_type = f"texture_{surface_type}"
        elif artifact_counts["dust"] + artifact_counts["shadow_patch"] > 18:
            hard_negative_type = "dark_spot_artifacts"
        else:
            hard_negative_type = "background"
    return image, boxes, {
        "scenario": surface_type,
        "candidate_label": "mosquito_visible" if boxes else "hard_negative",
        "hard_negative_type": hard_negative_type,
        "near_miss_insects": near_miss_count,
        "artifact_counts": artifact_counts,
        "wide_search_positive": bool(boxes) and split == "reality2017",
    }


def write_coco(output_dir: Path, split: str, images: list[dict[str, Any]], boxes_by_image: dict[int, list[Box]]) -> None:
    annotations = []
    ann_id = 1
    for image in images:
        for box in boxes_by_image.get(int(image["id"]), []):
            bbox = box.to_model_xywh(PHONE_SIZE[0], PHONE_SIZE[1])
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": image["id"],
                    "category_id": CLASS_ID,
                    "bbox": bbox,
                    "area": round(bbox[2] * bbox[3], 3),
                    "iscrowd": 0,
                    "source_phone_box": [
                        round(box.x1, 2),
                        round(box.y1, 2),
                        round(box.x2 - box.x1, 2),
                        round(box.y2 - box.y1, 2),
                    ],
                }
            )
            ann_id += 1
    payload = {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": CLASS_ID, "name": CLASS_NAME, "supercategory": "insect"}],
    }
    ann_dir = output_dir / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    (ann_dir / f"instances_{split}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_split(
    output_dir: Path,
    split: str,
    count: int,
    positive_ratio: float,
    rng: random.Random,
    save_phone_frames: bool,
) -> dict[str, Any]:
    model_dir = output_dir / split
    model_dir.mkdir(parents=True, exist_ok=True)
    phone_dir = output_dir / "phone_frames" / split
    if save_phone_frames:
        phone_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict[str, Any]] = []
    boxes_by_image: dict[int, list[Box]] = {}
    for index in range(1, count + 1):
        positive = rng.random() < positive_ratio
        phone_image, boxes, frame_meta = make_phone_frame(rng, positive, split)
        model_image = phone_image.resize((MODEL_SIZE, MODEL_SIZE), Image.Resampling.BILINEAR)
        file_name = f"{split}_{index:06d}.jpg"
        model_image.save(model_dir / file_name, quality=rng.randint(82, 95))
        if save_phone_frames:
            phone_image.save(phone_dir / file_name, quality=88)
        images.append(
            {
                "id": index,
                "file_name": file_name,
                "width": MODEL_SIZE,
                "height": MODEL_SIZE,
                "source_width": PHONE_SIZE[0],
                "source_height": PHONE_SIZE[1],
                "synthetic_phone_frame": True,
                "negative_only": not bool(boxes),
                **frame_meta,
            }
        )
        boxes_by_image[index] = boxes

    write_coco(output_dir, split, images, boxes_by_image)
    return {
        "images": len(images),
        "positive_images": sum(1 for boxes in boxes_by_image.values() if boxes),
        "negative_images": sum(1 for boxes in boxes_by_image.values() if not boxes),
        "boxes": sum(len(boxes) for boxes in boxes_by_image.values()),
    }


def main() -> None:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    np.random.seed(args.seed)

    splits = {
        "train2017": build_split(output_dir, "train2017", args.train_count, args.positive_ratio, rng, args.save_phone_frames),
        "val2017": build_split(output_dir, "val2017", args.val_count, args.positive_ratio, rng, args.save_phone_frames),
        "reality2017": build_split(output_dir, "reality2017", args.reality_count, args.reality_positive_ratio, rng, args.save_phone_frames),
    }
    summary = {
        "output_dir": str(output_dir),
        "format": "coco",
        "phone_size": PHONE_SIZE,
        "model_size": MODEL_SIZE,
        "class_name": CLASS_NAME,
        "seed": args.seed,
        "positive_ratio": args.positive_ratio,
        "reality_positive_ratio": args.reality_positive_ratio,
        "splits": splits,
        "notes": [
            "Phone frames are rendered at 1080x1920 then stretched to 416x416 to match Stage1Detector.resize.",
            "COCO boxes are exact projections from the phone coordinate system to the model coordinate system.",
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
