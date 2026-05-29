#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "synthetic"
IMAGE_SIZE = 224


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate deterministic wall-dot samples for Stage 2 mosquito training."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--positive-count", type=int, default=600)
    parser.add_argument("--negative-count", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260529)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous generated jpg files from the output directory first.",
    )
    return parser


def clamp_channel(values: np.ndarray) -> np.ndarray:
    return np.clip(values, 0, 255).astype(np.uint8)


def generate_wall_background(rng: random.Random) -> Image.Image:
    base_color = rng.randint(205, 252)
    pixels = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), base_color, dtype=np.int16)

    fine_noise = np.random.normal(0, rng.uniform(2.5, 8.0), pixels.shape)
    horizontal = np.linspace(
        rng.uniform(-10, 6),
        rng.uniform(-6, 10),
        IMAGE_SIZE,
        dtype=np.float32,
    )
    vertical = np.linspace(
        rng.uniform(-8, 8),
        rng.uniform(-8, 8),
        IMAGE_SIZE,
        dtype=np.float32,
    )
    gradient = horizontal[None, :, None] + vertical[:, None, None]

    pixels = pixels + fine_noise + gradient
    return Image.fromarray(clamp_channel(pixels), mode="RGB").filter(
        ImageFilter.GaussianBlur(radius=rng.uniform(0.0, 0.45))
    )


def add_flash_shadow(
    image: Image.Image,
    center: tuple[int, int],
    body_radius: int,
    rng: random.Random,
) -> None:
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    dx = rng.choice([-1, 1]) * rng.randint(3, 9)
    dy = rng.choice([-1, 1]) * rng.randint(2, 8)
    sx, sy = center[0] + dx, center[1] + dy
    shadow_radius = body_radius + rng.randint(1, 4)
    alpha = rng.randint(34, 92)
    draw.ellipse(
        [
            sx - shadow_radius,
            sy - shadow_radius,
            sx + shadow_radius,
            sy + shadow_radius,
        ],
        fill=(0, 0, 0, alpha),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=rng.uniform(1.1, 2.8)))
    image.paste(shadow, (0, 0), shadow)


def draw_mosquito(image: Image.Image, rng: random.Random) -> Image.Image:
    draw = ImageDraw.Draw(image)
    x = IMAGE_SIZE // 2 + rng.randint(-24, 24)
    y = IMAGE_SIZE // 2 + rng.randint(-24, 24)
    body_radius = rng.randint(3, 7)

    add_flash_shadow(image, (x, y), body_radius, rng)

    body_color = rng.randint(8, 38)
    draw.ellipse(
        [x - body_radius, y - body_radius, x + body_radius, y + body_radius],
        fill=(body_color, body_color, body_color),
    )

    wing_alpha = rng.randint(22, 58)
    wing = Image.new("RGBA", image.size, (0, 0, 0, 0))
    wing_draw = ImageDraw.Draw(wing)
    wing_draw.ellipse(
        [x - body_radius - 7, y - body_radius - 3, x - 1, y + body_radius + 2],
        fill=(45, 45, 45, wing_alpha),
    )
    wing_draw.ellipse(
        [x + 1, y - body_radius - 2, x + body_radius + 7, y + body_radius + 3],
        fill=(45, 45, 45, wing_alpha),
    )
    image.paste(wing, (0, 0), wing)

    leg_color = rng.randint(12, 42)
    for angle in (-55, -28, 28, 55):
        length = rng.randint(7, 14)
        radians = np.deg2rad(angle + rng.randint(-8, 8))
        x2 = int(x + np.cos(radians) * length)
        y2 = int(y + np.sin(radians) * length)
        draw.line([(x, y), (x2, y2)], fill=(leg_color, leg_color, leg_color), width=1)

    return image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.0, 0.75)))


def draw_hard_negative(image: Image.Image, rng: random.Random) -> Image.Image:
    draw = ImageDraw.Draw(image)
    if rng.random() < 0.78:
        x = IMAGE_SIZE // 2 + rng.randint(-28, 28)
        y = IMAGE_SIZE // 2 + rng.randint(-28, 28)
        radius = rng.randint(2, 10)
        shade = rng.randint(35, 110)
        if rng.random() < 0.65:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(shade, shade, shade))
        else:
            points = [
                (x + rng.randint(-radius, radius), y + rng.randint(-radius, radius))
                for _ in range(rng.randint(5, 9))
            ]
            draw.polygon(points, fill=(shade, shade, shade))

    for _ in range(rng.randint(0, 6)):
        x = rng.randint(0, IMAGE_SIZE - 1)
        y = rng.randint(0, IMAGE_SIZE - 1)
        shade = rng.randint(115, 190)
        draw.point((x, y), fill=(shade, shade, shade))

    return image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.0, 0.55)))


def save_sample(image: Image.Image, output_dir: Path, label: str, index: int) -> None:
    filename = f"20260529_SYN_wall_1x_torchon_{label}_{index:04d}.jpg"
    image.save(output_dir / filename, quality=92)


def main() -> None:
    args = build_parser().parse_args()
    rng = random.Random(args.seed)
    np.random.seed(args.seed)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for path in args.output_dir.glob("*.jpg"):
            path.unlink()
        legacy_dir = REPO_ROOT / "training" / "data" / "synthetic_v2"
        if legacy_dir.exists():
            shutil.rmtree(legacy_dir)

    for index in range(args.positive_count):
        save_sample(draw_mosquito(generate_wall_background(rng), rng), args.output_dir, "mosquito", index)

    for index in range(args.negative_count):
        save_sample(draw_hard_negative(generate_wall_background(rng), rng), args.output_dir, "hardnegative", index)

    print(
        f"Generated {args.positive_count + args.negative_count} samples in {args.output_dir}"
    )


if __name__ == "__main__":
    main()
