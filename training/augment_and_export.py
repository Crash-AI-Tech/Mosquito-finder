#!/usr/bin/env python3
"""
augment_and_export.py
数据增强（×10）+ 训练 + CoreML 导出，一键运行。

从 data/synthetic/ 的现有图片出发，对每张生成 N_AUG 份随机增强版本，
总数据量约 10×，再训练 Scaler → PCA → LogReg 管道，
导出为 Mosquito-finder/MosquitoClassifier.mlmodel（GRAYSCALE 64×64）。

Usage:
    .venv/bin/python training/augment_and_export.py
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ─── 路径 ─────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
DATA_DIR    = REPO_ROOT / "data" / "synthetic"
OUTPUT_PATH = REPO_ROOT / "Mosquito-finder" / "MosquitoClassifier.mlmodel"

IMAGE_SIZE = 64    # 必须与 CoreML input spec 一致
N_AUG      = 10   # 每张图片生成多少份增强 → 总量 ≈ 原始×11
SEED       = 42

LABEL_TO_BINARY: dict[str, int] = {
    "mosquito":    1,
    "notmosquito": 0,
    "hardnegative": 0,
}

FILENAME_PATTERN = re.compile(
    r"\d{8}_"
    r"[^_]+_"           # source
    r"[^_]+_"           # scene
    r"[^_]+_"           # zoom
    r"[^_]+_"           # torch
    r"(?P<label>mosquito|notmosquito|hardnegative|uncertain)_"
    r"\d+"              # index
    r"(?:_.*)?"         # optional variant suffix
)

# ─── 数据增强 ─────────────────────────────────────────────────────────────────

def _fill_color(img: Image.Image) -> int | tuple[int, ...]:
    """取图片左上角像素作为旋转/裁剪的填充色。"""
    px = img.getpixel((0, 0))
    if isinstance(px, int):
        return px
    return px[:img.mode.count("A") and -1 or len(px)]  # drop alpha if present


def augment(img: Image.Image, rng: random.Random) -> Image.Image:
    """对一张 PIL 图片施加随机增强，返回增强后的图片（原图不被修改）。"""
    img = img.copy()

    # 1. 随机水平翻转（50%）
    if rng.random() > 0.5:
        img = ImageOps.mirror(img)

    # 2. 随机垂直翻转（30%）
    if rng.random() > 0.7:
        img = ImageOps.flip(img)

    # 3. 随机旋转 ±20°
    angle = rng.uniform(-20, 20)
    img = img.rotate(
        angle,
        resample=Image.Resampling.BILINEAR,
        expand=False,
        fillcolor=_fill_color(img),
    )

    # 4. 随机亮度 0.5 – 1.7
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.5, 1.7))

    # 5. 随机对比度 0.55 – 1.65
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.55, 1.65))

    # 6. 随机锐度 0.3 – 2.8
    img = ImageEnhance.Sharpness(img).enhance(rng.uniform(0.3, 2.8))

    # 7. 随机滤波（模糊 / 锐化，各 20% 概率）
    r = rng.random()
    if r < 0.20:
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.5, 1.8)))
    elif r < 0.40:
        img = img.filter(ImageFilter.SHARPEN)

    # 8. 随机高斯噪声（55% 概率）
    if rng.random() > 0.45:
        arr = np.asarray(img).astype(np.float32)
        sigma = rng.uniform(4, 22)
        noise_rng = np.random.default_rng(rng.randint(0, 0xFFFF))
        noise = noise_rng.normal(0, sigma, arr.shape)
        arr = np.clip(arr + noise, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), mode=img.mode)

    # 9. 随机裁剪 + 缩放（80-99%，50% 概率）
    if rng.random() > 0.5:
        w, h = img.size
        ratio = rng.uniform(0.80, 0.99)
        nw, nh = max(4, int(w * ratio)), max(4, int(h * ratio))
        x0 = rng.randint(0, w - nw)
        y0 = rng.randint(0, h - nh)
        img = img.crop((x0, y0, x0 + nw, y0 + nh)).resize(
            (w, h), Image.Resampling.BILINEAR
        )

    # 10. 随机 Gamma 变换（40% 概率）
    if rng.random() > 0.6:
        gamma = rng.uniform(0.55, 1.9)
        arr = (np.asarray(img).astype(np.float32) / 255.0) ** gamma * 255.0
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode=img.mode)

    return img


# ─── 特征提取（与 CoreML 前向一致：灰度 64×64 展平） ────────────────────────

def pixel_features(img: Image.Image) -> np.ndarray:
    """将图片转灰度、缩放到 IMAGE_SIZE²，返回展平的 float32 特征向量。"""
    gray = img.convert("L").resize(
        (IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR
    )
    return np.asarray(gray, dtype=np.float32).flatten() / 255.0


# ─── 数据集加载 ───────────────────────────────────────────────────────────────

def load_dataset() -> tuple[np.ndarray, np.ndarray]:
    """
    读取 DATA_DIR 中所有 .jpg，对每张生成 N_AUG 份增强。
    返回 (X: float32 矩阵, y: int32 标签向量)。
    """
    rng = random.Random(SEED)
    X_list: list[np.ndarray] = []
    y_list: list[int] = []

    image_paths = sorted(DATA_DIR.glob("*.jpg"))
    if not image_paths:
        raise FileNotFoundError(f"data/synthetic/ 中没有找到 .jpg 图片: {DATA_DIR}")

    n_total_expect = len(image_paths) * (N_AUG + 1)
    print(f"[数据集] 找到 {len(image_paths)} 张图片，每张增强 {N_AUG} 份")
    print(f"         预计总样本数: {n_total_expect}")

    skipped = 0
    for path in image_paths:
        match = FILENAME_PATTERN.fullmatch(path.stem)
        if match is None:
            skipped += 1
            continue
        label_str = match.group("label")
        y = LABEL_TO_BINARY.get(label_str, -1)
        if y < 0:  # uncertain → skip
            skipped += 1
            continue

        with Image.open(path) as im:
            base_img = im.convert("RGB").copy()

        # 原始图
        X_list.append(pixel_features(base_img))
        y_list.append(y)

        # 增强图
        for _ in range(N_AUG):
            aug = augment(base_img, rng)
            X_list.append(pixel_features(aug))
            y_list.append(y)

    if skipped:
        print(f"         跳过 {skipped} 张（文件名格式不匹配或 uncertain 标签）")

    X = np.vstack(X_list).astype(np.float32)
    y = np.array(y_list, dtype=np.int32)

    pos = int(y.sum())
    neg = int((y == 0).sum())
    print(f"[数据集] 最终: {X.shape[0]} 样本  正(蚊子)={pos}  负={neg}\n")
    return X, y


# ─── 训练 ─────────────────────────────────────────────────────────────────────

def train_pipeline(X: np.ndarray, y: np.ndarray):
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    n_samples, n_features = X.shape
    # 增大 PCA 维度以保留更多判别信息
    n_pca = min(64, n_features, n_samples - 1)

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("pca",    PCA(n_components=n_pca, random_state=SEED)),
        ("lr",     LogisticRegression(
            class_weight="balanced",   # 自动平衡正负样本权重
            C=0.3,                     # 适度正则化，避免在小数据集过拟合
            max_iter=10000,
            random_state=SEED,
            solver="liblinear",
        )),
    ])

    print(f"[训练] Scaler → PCA({n_pca}) → LogReg(balanced, C=0.3) ...")
    t0 = time.time()
    pipe.fit(X, y)
    elapsed = time.time() - t0

    train_acc  = (pipe.predict(X) == y).mean()
    train_prec = (pipe.predict_proba(X)[:, 1] >= 0.5).astype(int)
    pos_recall = train_prec[y == 1].mean() if y.sum() > 0 else 0.0
    print(f"[训练] 完成  耗时={elapsed:.1f}s  全集准确率={train_acc:.3f}  正类召回={pos_recall:.3f}")
    return pipe


# ─── CoreML 导出 ───────────────────────────────────────────────────────────────

def export_coreml(pipe, size: tuple[int, int], output_path: Path) -> None:
    from coremltools.proto import FeatureTypes_pb2, Model_pb2  # type: ignore

    scaler = pipe.named_steps["scaler"]
    pca    = pipe.named_steps["pca"]
    lr     = pipe.named_steps["lr"]

    H, W  = size
    N     = H * W          # 4096
    n_pca = pca.n_components_
    CLASS_LABELS = ["not_mosquito", "mosquito"]   # index 0=负, 1=正

    # ── 权重矩阵 ──────────────────────────────────────────────────────────────
    # ScaleLayer: raw pixel x ∈ [0,255] → StandardScaler 归一化
    scale_w = (1.0 / (255.0 * scaler.scale_)).astype(np.float32)  # (N,)
    scale_b = (-scaler.mean_ / scaler.scale_).astype(np.float32)   # (N,)

    # InnerProduct PCA: x_pca = scaler_out @ components_.T + bias
    W_pca = pca.components_.astype(np.float32)                      # (n_pca, N)
    b_pca = (-pca.mean_ @ pca.components_.T).astype(np.float32)    # (n_pca,)

    # InnerProduct LR: 2 输出（not_mosquito, mosquito）
    W_lr_1 = lr.coef_.astype(np.float32)                            # (1, n_pca)
    b_lr_1 = lr.intercept_.astype(np.float32)                       # (1,)
    W_lr   = np.vstack([-W_lr_1, W_lr_1])                          # (2, n_pca)
    b_lr   = np.array([-b_lr_1[0], b_lr_1[0]], dtype=np.float32)  # (2,)

    # ── 构建 ModelSpec ────────────────────────────────────────────────────────
    spec = Model_pb2.Model()
    spec.specificationVersion = 4  # CoreML 4 / iOS 14+

    # 输入: GRAYSCALE 图像
    img_in = spec.description.input.add()
    img_in.name = "image"
    img_in.type.imageType.width      = W
    img_in.type.imageType.height     = H
    img_in.type.imageType.colorSpace = FeatureTypes_pb2.ImageFeatureType.GRAYSCALE

    # 输出 1: classLabel (String)
    lbl_out = spec.description.output.add()
    lbl_out.name = "classLabel"
    lbl_out.type.stringType.SetInParent()

    # 输出 2: classLabelProbs (Dictionary<String,Double>)
    prob_out = spec.description.output.add()
    prob_out.name = "classLabelProbs"
    prob_out.type.dictionaryType.stringKeyType.SetInParent()

    spec.description.predictedFeatureName       = "classLabel"
    spec.description.predictedProbabilitiesName = "classLabelProbs"

    # 分类器
    nn = spec.neuralNetworkClassifier
    nn.stringClassLabels.vector.extend(CLASS_LABELS)

    # Layer 1 – Flatten: (1,H,W) → (N,1,1)
    flat = nn.layers.add()
    flat.name = "flatten"
    flat.input.append("image")
    flat.output.append("flat")
    flat.flatten.mode = 0  # CHANNEL_FIRST

    # Layer 2 – Scale+bias (StandardScaler)
    sc = nn.layers.add()
    sc.name = "normalize"
    sc.input.append("flat")
    sc.output.append("scaled")
    sc.scale.scale.floatValue.extend(scale_w.tolist())
    sc.scale.shapeScale.extend([N, 1, 1])
    sc.scale.hasBias = True
    sc.scale.bias.floatValue.extend(scale_b.tolist())
    sc.scale.shapeBias.extend([N, 1, 1])

    # Layer 3 – InnerProduct (PCA): (N,) → (n_pca,)
    ip1 = nn.layers.add()
    ip1.name = "pca"
    ip1.input.append("scaled")
    ip1.output.append("pca_out")
    ip1.innerProduct.inputChannels  = N
    ip1.innerProduct.outputChannels = n_pca
    ip1.innerProduct.hasBias        = True
    ip1.innerProduct.weights.floatValue.extend(W_pca.flatten().tolist())
    ip1.innerProduct.bias.floatValue.extend(b_pca.tolist())

    # Layer 4 – InnerProduct (LR head): (n_pca,) → (2,)
    ip2 = nn.layers.add()
    ip2.name = "lr"
    ip2.input.append("pca_out")
    ip2.output.append("logits")
    ip2.innerProduct.inputChannels  = n_pca
    ip2.innerProduct.outputChannels = 2
    ip2.innerProduct.hasBias        = True
    ip2.innerProduct.weights.floatValue.extend(W_lr.flatten().tolist())
    ip2.innerProduct.bias.floatValue.extend(b_lr.tolist())

    # Layer 5 – Softmax: → classLabelProbs
    sm = nn.layers.add()
    sm.name = "softmax"
    sm.input.append("logits")
    sm.output.append("classLabelProbs")
    sm.softmax.SetInParent()

    # 元数据
    spec.description.metadata.shortDescription = (
        f"Mosquito Finder Stage-2 (augmented ×{N_AUG + 1}). "
        f"Input: GRAYSCALE {W}x{H}. "
        "Output: classLabel in {mosquito, not_mosquito}."
    )
    spec.description.metadata.author = "Mosquito Finder ML Pipeline"
    spec.description.metadata.versionString = "2.0-aug"

    # 保存（直接写 protobuf 字节，兼容任意 coremltools 版本）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(output_path), "wb") as fh:
        fh.write(spec.SerializeToString())

    print(f"[导出] CoreML 模型已保存: {output_path}")
    print(f"       架构: GRAY{W}x{H} → Flatten({N}) → Scaler → PCA({n_pca}) → LR(2) → Softmax")
    print(f"       标签: {CLASS_LABELS}")


# ─── 主程序 ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Mosquito Finder  数据增强 + 训练 + CoreML 导出")
    print(f"数据目录 : {DATA_DIR}")
    print(f"输出模型 : {OUTPUT_PATH}")
    print(f"增强倍数 : {N_AUG + 1}x  (原始 1 + 增强 {N_AUG})")
    print("=" * 60)

    t_total = time.time()

    X, y = load_dataset()
    pipe  = train_pipeline(X, y)
    export_coreml(pipe, (IMAGE_SIZE, IMAGE_SIZE), OUTPUT_PATH)

    print(f"\n总耗时: {time.time() - t_total:.1f}s")
    print("完成！请在 Xcode 中 Clean Build Folder 后重新编译以更新模型。")


if __name__ == "__main__":
    main()
