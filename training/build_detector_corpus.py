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
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "detector" / "generated"
IMAGE_SIZE = 416
CLASS_ID = 1
CLASS_NAME = "mosquito"


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_coco(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    def to_yolo(self) -> str:
        cx = (self.x + self.width / 2) / IMAGE_SIZE
        cy = (self.y + self.height / 2) / IMAGE_SIZE
        width = self.width / IMAGE_SIZE
        height = self.height / IMAGE_SIZE
        return f"0 {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a zero-cost mosquito detector corpus with COCO and YOLO labels."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-count", type=int, default=1600)
    parser.add_argument("--val-count", type=int, default=320)
    parser.add_argument("--reality-count", type=int, default=480)
    parser.add_argument("--positive-ratio", type=float, default=0.52)
    parser.add_argument("--seed", type=int, default=20260530)
    parser.add_argument(
        "--zero-category-id",
        action="store_true",
        help="Use category id 0 in COCO annotations for D-FINE custom training.",
    )
    parser.add_argument("--clean", action="store_true")
    return parser


def clamp(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 0, 255).astype(np.uint8)


def background_wall(rng: random.Random) -> Image.Image:
    base = rng.randint(190, 250)
    pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), base, dtype=np.float32)
    noise = np.random.normal(0, rng.uniform(2.0, 10.0), pixels.shape)
    x_grad = np.linspace(rng.uniform(-18, 10), rng.uniform(-8, 18), IMAGE_SIZE)
    y_grad = np.linspace(rng.uniform(-16, 16), rng.uniform(-16, 16), IMAGE_SIZE)
    pixels += noise + x_grad[None, :, None] + y_grad[:, None, None]
    return Image.fromarray(clamp(pixels), "RGB").filter(
        ImageFilter.GaussianBlur(rng.uniform(0, 0.8))
    )


def background_wood(rng: random.Random) -> Image.Image:
    base = np.zeros((IMAGE_SIZE, IMAGE_SIZE, 3), dtype=np.float32)
    tone = rng.randint(92, 178)
    base[:, :, 0] = tone + rng.randint(12, 42)
    base[:, :, 1] = tone * rng.uniform(0.62, 0.82)
    base[:, :, 2] = tone * rng.uniform(0.34, 0.56)
    for x in range(0, IMAGE_SIZE, rng.randint(16, 36)):
        stripe = rng.uniform(-24, 24)
        base[:, x : x + rng.randint(4, 12), :] += stripe
    wave = np.sin(np.linspace(0, rng.uniform(8, 18), IMAGE_SIZE))[None, :, None] * rng.uniform(7, 18)
    base += wave
    base += np.random.normal(0, rng.uniform(3, 10), base.shape)
    return Image.fromarray(clamp(base), "RGB").filter(ImageFilter.GaussianBlur(rng.uniform(0, 0.6)))


def background_fabric(rng: random.Random) -> Image.Image:
    palette = rng.choice([(210, 210, 205), (178, 188, 205), (205, 196, 182), (190, 205, 198)])
    pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), palette, dtype=np.float32)
    for step in (rng.randint(5, 9), rng.randint(9, 15)):
        for x in range(0, IMAGE_SIZE, step):
            pixels[:, x : x + 1, :] -= rng.uniform(6, 18)
        for y in range(0, IMAGE_SIZE, step + rng.randint(1, 4)):
            pixels[y : y + 1, :, :] -= rng.uniform(4, 14)
    pixels += np.random.normal(0, rng.uniform(4, 12), pixels.shape)
    return Image.fromarray(clamp(pixels), "RGB").filter(ImageFilter.GaussianBlur(rng.uniform(0.1, 0.7)))


def background_tile_or_screen(rng: random.Random) -> Image.Image:
    base = rng.randint(170, 236)
    pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), base, dtype=np.float32)
    grid = rng.randint(52, 94)
    line_color = base - rng.randint(12, 36)
    for x in range(rng.randint(0, grid), IMAGE_SIZE, grid):
        pixels[:, max(0, x - 1) : min(IMAGE_SIZE, x + 2), :] = line_color
    for y in range(rng.randint(0, grid), IMAGE_SIZE, grid):
        pixels[max(0, y - 1) : min(IMAGE_SIZE, y + 2), :, :] = line_color
    pixels += np.random.normal(0, rng.uniform(2, 11), pixels.shape)
    image = Image.fromarray(clamp(pixels), "RGB")
    if rng.random() < 0.45:
        image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.65, 1.45))
    return image


def background_painted_corner(rng: random.Random) -> Image.Image:
    base = rng.randint(176, 246)
    pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), base, dtype=np.float32)
    pixels += np.random.normal(0, rng.uniform(3, 14), pixels.shape)

    # Subtle room edges, stains, and flashlight falloff match the real hunting flow.
    if rng.random() < 0.55:
        edge = rng.randint(72, 340)
        pixels[:, max(0, edge - 2) : min(IMAGE_SIZE, edge + 2), :] -= rng.uniform(10, 34)
    if rng.random() < 0.45:
        edge = rng.randint(72, 340)
        pixels[max(0, edge - 2) : min(IMAGE_SIZE, edge + 2), :, :] -= rng.uniform(8, 28)
    for _ in range(rng.randint(1, 6)):
        x = rng.randint(0, IMAGE_SIZE - 1)
        y = rng.randint(0, IMAGE_SIZE - 1)
        radius = rng.randint(18, 92)
        stain = Image.new("L", (IMAGE_SIZE, IMAGE_SIZE), 0)
        stain_draw = ImageDraw.Draw(stain)
        stain_draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=rng.randint(12, 42))
        stain = stain.filter(ImageFilter.GaussianBlur(rng.uniform(12, 32)))
        pixels -= np.asarray(stain)[:, :, None] * rng.uniform(0.25, 0.9)

    yy, xx = np.mgrid[:IMAGE_SIZE, :IMAGE_SIZE]
    cx = rng.randint(80, 335)
    cy = rng.randint(80, 335)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    falloff = np.clip((dist - rng.randint(90, 150)) / rng.randint(170, 260), 0, 1)
    pixels *= 1.0 - falloff[:, :, None] * rng.uniform(0.18, 0.48)
    return Image.fromarray(clamp(pixels), "RGB").filter(ImageFilter.GaussianBlur(rng.uniform(0, 0.7)))


def build_background(rng: random.Random) -> Image.Image:
    builder = rng.choices(
        [
            background_wall,
            background_wood,
            background_fabric,
            background_tile_or_screen,
            background_painted_corner,
        ],
        weights=[0.32, 0.16, 0.18, 0.14, 0.20],
        k=1,
    )[0]
    image = builder(rng)
    if rng.random() < 0.55:
        image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.55, 1.35))
    if rng.random() < 0.65:
        image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.75, 1.55))
    return image


def draw_smudge(draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    x = rng.randint(20, IMAGE_SIZE - 20)
    y = rng.randint(20, IMAGE_SIZE - 20)
    r = rng.randint(2, 16)
    shade = rng.randint(25, 135)
    if rng.random() < 0.55:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(shade, shade, shade))
    else:
        points = [(x + rng.randint(-r, r), y + rng.randint(-r, r)) for _ in range(rng.randint(4, 10))]
        draw.polygon(points, fill=(shade, shade, shade))


def draw_hard_negatives(image: Image.Image, rng: random.Random) -> None:
    draw = ImageDraw.Draw(image)
    for _ in range(rng.randint(2, 12)):
        if rng.random() < 0.34:
            draw_smudge(draw, rng)
        elif rng.random() < 0.64:
            x = rng.randint(15, IMAGE_SIZE - 15)
            y = rng.randint(15, IMAGE_SIZE - 15)
            length = rng.randint(8, 54)
            angle = rng.uniform(0, math.pi * 2)
            x2 = int(x + math.cos(angle) * length)
            y2 = int(y + math.sin(angle) * length)
            shade = rng.randint(40, 150)
            draw.line([(x, y), (x2, y2)], fill=(shade, shade, shade), width=rng.randint(1, 2))
        else:
            x = rng.randint(0, IMAGE_SIZE - 1)
            y = rng.randint(0, IMAGE_SIZE - 1)
            shade = rng.randint(0, 80)
            draw.point((x, y), fill=(shade, shade, shade))

    # Near-miss insects and wall artifacts: these are what caused false positives in app testing.
    for _ in range(rng.randint(0, 5)):
        x = rng.randint(20, IMAGE_SIZE - 20)
        y = rng.randint(20, IMAGE_SIZE - 20)
        shade = rng.randint(15, 95)
        radius = rng.randint(2, 8)
        if rng.random() < 0.5:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(shade, shade, shade))
            for side in (-1, 1):
                draw.line([(x, y), (x + side * rng.randint(8, 22), y + rng.randint(-8, 8))], fill=(shade, shade, shade), width=1)
        else:
            draw.rectangle([x, y, x + rng.randint(4, 18), y + rng.randint(1, 4)], fill=(shade, shade, shade))


def draw_mosquito(image: Image.Image, rng: random.Random) -> Box:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Real phone frames often see the mosquito as a tiny 8-30 px target.
    if rng.random() < 0.62:
        body_w = rng.randint(3, 9)
        body_h = rng.randint(6, 20)
    else:
        body_w = rng.randint(8, 15)
        body_h = rng.randint(18, 34)
    cx = rng.randint(42, IMAGE_SIZE - 42)
    cy = rng.randint(42, IMAGE_SIZE - 42)
    angle = rng.uniform(-math.pi, math.pi)
    dark = rng.randint(8, 48)

    shadow_offset = rng.randint(2, 10)
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        [
            cx - body_w + shadow_offset,
            cy - body_h + shadow_offset,
            cx + body_w + shadow_offset,
            cy + body_h + shadow_offset,
        ],
        fill=(0, 0, 0, rng.randint(18, 72)),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(rng.uniform(1.2, 3.2)))
    image.paste(shadow, (0, 0), shadow)

    def rotate_point(px: float, py: float) -> tuple[int, int]:
        rx = math.cos(angle) * px - math.sin(angle) * py
        ry = math.sin(angle) * px + math.cos(angle) * py
        return int(cx + rx), int(cy + ry)

    # Legs first, then translucent wings, then body/head.
    for side in (-1, 1):
        for anchor_y in (-0.35, 0.0, 0.35):
            start = rotate_point(side * body_w * 0.35, anchor_y * body_h)
            knee = rotate_point(side * rng.uniform(8, 18), anchor_y * body_h + rng.uniform(-8, 8))
            end = rotate_point(side * rng.uniform(16, 34), anchor_y * body_h + rng.uniform(-18, 18))
            draw.line([start, knee, end], fill=(dark, dark, dark, rng.randint(150, 235)), width=1)

    wing_alpha = rng.randint(22, 78)
    for side in (-1, 1):
        wx, wy = rotate_point(side * body_w * 0.85, -body_h * 0.15)
        draw.ellipse(
            [
                wx - rng.randint(7, 14),
                wy - rng.randint(5, 12),
                wx + rng.randint(7, 14),
                wy + rng.randint(9, 18),
            ],
            fill=(58, 58, 58, wing_alpha),
        )

    draw.ellipse(
        [cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 2],
        fill=(dark, dark, dark, rng.randint(220, 255)),
    )
    head = rotate_point(0, -body_h * 0.64)
    head_r = max(2, body_w // 3)
    draw.ellipse([head[0] - head_r, head[1] - head_r, head[0] + head_r, head[1] + head_r], fill=(dark, dark, dark, 235))

    if rng.random() < 0.35:
        layer = layer.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.9)))
    image.paste(layer, (0, 0), layer)

    alpha = np.asarray(layer.split()[-1])
    ys, xs = np.where(alpha > 12)
    pad = rng.randint(2, 6)
    x1 = max(0, int(xs.min()) - pad)
    y1 = max(0, int(ys.min()) - pad)
    x2 = min(IMAGE_SIZE - 1, int(xs.max()) + pad)
    y2 = min(IMAGE_SIZE - 1, int(ys.max()) + pad)
    return Box(x=x1, y=y1, width=max(2, x2 - x1), height=max(2, y2 - y1))


def save_image(image: Image.Image, path: Path, rng: random.Random) -> None:
    if rng.random() < 0.55:
        # Phone sensor noise + compression/sharpening artifacts.
        arr = np.asarray(image).astype(np.float32)
        arr += np.random.normal(0, rng.uniform(1.5, 7.5), arr.shape)
        image = Image.fromarray(clamp(arr), "RGB")
    if rng.random() < 0.35:
        image = ImageEnhance.Sharpness(image).enhance(rng.uniform(0.55, 1.85))
    if rng.random() < 0.40:
        image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 0.55)))
    image.save(path, quality=rng.randint(82, 96))


def make_sample(split: str, index: int, positive: bool, output_dir: Path, rng: random.Random) -> dict[str, Any]:
    image = build_background(rng)
    draw_hard_negatives(image, rng)

    boxes: list[Box] = []
    if positive:
        for _ in range(1 if rng.random() < 0.86 else 2):
            boxes.append(draw_mosquito(image, rng))

    file_name = f"{split}_{index:05d}.jpg"
    image_dir = output_dir / split
    image_dir.mkdir(parents=True, exist_ok=True)
    save_image(image, image_dir / file_name, rng)

    return {
        "id": index,
        "file_name": file_name,
        "width": IMAGE_SIZE,
        "height": IMAGE_SIZE,
        "boxes": boxes,
    }


def write_coco(
    annotation_dir: Path,
    split_name: str,
    samples: list[dict[str, Any]],
    category_id: int,
) -> None:
    annotations = []
    ann_id = 1
    for sample in samples:
        for box in sample["boxes"]:
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": sample["id"],
                    "category_id": category_id,
                    "bbox": box.to_coco(),
                    "area": box.area,
                    "iscrowd": 0,
                }
            )
            ann_id += 1

    payload = {
        "images": [
            {
                "id": sample["id"],
                "file_name": sample["file_name"],
                "width": IMAGE_SIZE,
                "height": IMAGE_SIZE,
            }
            for sample in samples
        ],
        "annotations": annotations,
        "categories": [{"id": category_id, "name": CLASS_NAME}],
    }
    annotation_dir.mkdir(parents=True, exist_ok=True)
    (annotation_dir / f"instances_{split_name}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def write_yolo_labels(output_dir: Path, split: str, samples: list[dict[str, Any]]) -> None:
    label_dir = output_dir / "labels" / split
    label_dir.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        rows = [box.to_yolo() for box in sample["boxes"]]
        (label_dir / f"{Path(sample['file_name']).stem}.txt").write_text(
            "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8"
        )


def build_split(
    split: str,
    count: int,
    positive_ratio: float,
    output_dir: Path,
    rng: random.Random,
) -> list[dict[str, Any]]:
    samples = []
    for index in range(1, count + 1):
        positive = rng.random() < positive_ratio
        samples.append(make_sample(split, index, positive, output_dir, rng))
    return samples


def main() -> None:
    args = build_parser().parse_args()
    rng = random.Random(args.seed)
    np.random.seed(args.seed)

    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    # YOLOX expects COCO-like train2017/val2017 under the dataset root.
    train_samples = build_split("train2017", args.train_count, args.positive_ratio, args.output_dir, rng)
    val_samples = build_split("val2017", args.val_count, args.positive_ratio, args.output_dir, rng)
    reality_samples = build_split("reality2017", args.reality_count, 0.28, args.output_dir, rng)

    ann_dir = args.output_dir / "annotations"
    category_id = 0 if args.zero_category_id else CLASS_ID
    write_coco(ann_dir, "train2017", train_samples, category_id)
    write_coco(ann_dir, "val2017", val_samples, category_id)
    write_coco(ann_dir, "reality2017", reality_samples, category_id)

    write_yolo_labels(args.output_dir, "train2017", train_samples)
    write_yolo_labels(args.output_dir, "val2017", val_samples)
    write_yolo_labels(args.output_dir, "reality2017", reality_samples)

    summary = {
        "image_size": IMAGE_SIZE,
        "class_names": [CLASS_NAME],
        "splits": {
            "train2017": {
                "images": len(train_samples),
                "positive_images": sum(1 for sample in train_samples if sample["boxes"]),
                "boxes": sum(len(sample["boxes"]) for sample in train_samples),
            },
            "val2017": {
                "images": len(val_samples),
                "positive_images": sum(1 for sample in val_samples if sample["boxes"]),
                "boxes": sum(len(sample["boxes"]) for sample in val_samples),
            },
            "reality2017": {
                "images": len(reality_samples),
                "positive_images": sum(1 for sample in reality_samples if sample["boxes"]),
                "boxes": sum(len(sample["boxes"]) for sample in reality_samples),
                "note": "Harder low-prevalence validation split for false-positive pressure.",
            },
        },
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
