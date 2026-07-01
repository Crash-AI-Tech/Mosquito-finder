# Mosquito Finder Data Engineering Pipeline

Updated: 2026-06-28

## Goal

The app scenario needs two different datasets:

1. Full-frame detector data for wide-area search.
   - Positive images: mosquito boxes.
   - Negative images: mosquito-free hard negatives with empty COCO annotations.

2. ROI classifier data for close-up confirmation.
   - Positive crops: expanded mosquito boxes.
   - Negative crops: random/background crops and detector false-positive style crops.

Do not create fake full-image boxes for image-level datasets. Mosquito Alert Tigapics should be used for classification, assisted annotation, or pseudo-label review, not as full-frame detector truth without boxes.

## Hard Negative COCO

Use this for indoor walls, ceilings, stains, dust, non-mosquito insects, and app false-positive review exports:

```bash
python3 training/build_hard_negative_coco.py \
  --source indoor_walls=data/external/hard_negatives/indoor_walls \
  --source other_insects=data/external/hard_negatives/other_insects \
  --output-dir data/processed/hard_negative_coco \
  --val-ratio 0.15 \
  --normalize-images \
  --clean
```

The output is standard COCO:

```text
data/processed/hard_negative_coco/
├── train2017/
├── val2017/
├── annotations/instances_train2017.json
├── annotations/instances_val2017.json
└── summary.json
```

Images have no annotations. Detector loaders should treat these as valid negative frames.

## Mixed Detector Dataset

Merge boxed mosquito data with hard negatives:

```bash
python3 training/build_real_detector_mix.py \
  --output-dir data/processed/real_detector_mix_hardneg_coco \
  --train-source kaggle=data/processed/kaggle_coco_single_class \
  --train-source huggingface=data/processed/huggingface_mosquito_coco_single_class \
  --val-source kaggle=data/processed/kaggle_coco_single_class \
  --train-negative-source hardneg=data/processed/hard_negative_coco \
  --val-negative-source hardneg=data/processed/hard_negative_coco \
  --min-box-size 4 \
  --clean
```

Use `--min-pseudo-score` only when a pseudo-labeled source is included.

## Stage 2 Classifier Crops

Build the close-up classifier manifest from the mixed detector dataset:

```bash
python3 training/build_classifier_crops_from_detector.py \
  --dataset-dir data/processed/real_detector_mix_hardneg_coco \
  --output-dir data/classifier/real_detector_crops_hardneg \
  --manifest artifacts/classifier_real_detector_crops_hardneg/manifest.csv \
  --negative-per-image 3 \
  --clean
```

Then train the classifier:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_cnn_classifier_coreml.py \
  --manifest artifacts/classifier_real_detector_crops_hardneg/manifest.csv \
  --output-dir artifacts/retrain_real/classifier_cnn_real_hardneg \
  --batch-size 2048 \
  --num-workers 4 \
  --epochs 32 \
  --device mps \
  --export-coreml
```

## Verified Smoke Run

On 2026-06-28, the pipeline was smoke-tested with existing classifier hard-negative crops:

```bash
python3 training/build_hard_negative_coco.py \
  --source classifier_hardnegative=data/classifier/real_detector_crops/hardnegative \
  --output-dir data/processed/hard_negative_coco_classifier_sample \
  --max-images-per-source 120 \
  --val-ratio 0.2 \
  --copy-images \
  --clean
```

Result:

- `train2017`: 90 negative-only images.
- `val2017`: 30 negative-only images.

Mixed detector sample:

```bash
python3 training/build_real_detector_mix.py \
  --output-dir data/processed/real_detector_mix_hardneg_sample_coco \
  --train-source kaggle=data/processed/kaggle_coco_single_class \
  --val-source kaggle=data/processed/kaggle_coco_single_class \
  --train-negative-source hardneg=data/processed/hard_negative_coco_classifier_sample \
  --val-negative-source hardneg=data/processed/hard_negative_coco_classifier_sample \
  --min-box-size 4 \
  --clean
```

Result:

- Train: 5997 mosquito boxes + 90 negative-only images.
- Val: 1489 mosquito boxes + 30 negative-only images.

Classifier crop smoke:

```bash
python3 training/build_classifier_crops_from_detector.py \
  --dataset-dir data/processed/real_detector_mix_hardneg_sample_coco \
  --output-dir data/classifier/real_detector_crops_hardneg_sample \
  --manifest artifacts/classifier_real_detector_crops_hardneg_sample/manifest.csv \
  --splits val2017 \
  --negative-per-image 1 \
  --clean
```

Result:

- 1489 mosquito ROI crops.
- 1579 hard-negative ROI crops.

## 2026-06-28 Rebuild Outputs

Full hard-negative pool:

```bash
python3 training/build_hard_negative_coco.py \
  --source detector_crops=data/classifier/real_detector_crops/hardnegative \
  --source pseudo_fixed_crops=data/classifier/real_detector_crops_pseudo_t050_s055_fixed_exif/hardnegative \
  --output-dir data/processed/hard_negative_coco_full \
  --val-ratio 0.15 \
  --seed 20260628 \
  --clean
```

Result:

- Train: 65,864 negative-only images.
- Val: 11,659 negative-only images.

Full detector mix:

```bash
python3 training/build_real_detector_mix.py \
  --output-dir data/processed/real_detector_mix_hardneg_full_coco \
  --train-source real_combined=data/processed/combined_mosquito_coco_single_class \
  --val-source real_combined=data/processed/combined_mosquito_coco_single_class \
  --train-negative-source hardneg=data/processed/hard_negative_coco_full \
  --val-negative-source hardneg=data/processed/hard_negative_coco_full \
  --min-box-size 4 \
  --clean
```

Result:

- Train: 8,591 positive images / 9,004 mosquito boxes + 65,864 negative-only images.
- Val: 1,955 positive images / 2,020 mosquito boxes + 11,659 negative-only images.

This full mix is useful for hard-negative mining, but it is not the recommended first training dataset because the negative-only ratio is high.

Recommended balanced detector mix:

```bash
python3 training/build_hard_negative_coco.py \
  --source detector_crops=data/classifier/real_detector_crops/hardnegative \
  --source pseudo_fixed_crops=data/classifier/real_detector_crops_pseudo_t050_s055_fixed_exif/hardnegative \
  --output-dir data/processed/hard_negative_coco_balanced \
  --max-images-per-source 6000 \
  --val-ratio 0.15 \
  --seed 20260628 \
  --clean

python3 training/build_real_detector_mix.py \
  --output-dir data/processed/real_detector_mix_hardneg_balanced_coco \
  --train-source real_combined=data/processed/combined_mosquito_coco_single_class \
  --val-source real_combined=data/processed/combined_mosquito_coco_single_class \
  --train-negative-source hardneg=data/processed/hard_negative_coco_balanced \
  --val-negative-source hardneg=data/processed/hard_negative_coco_balanced \
  --min-box-size 4 \
  --clean
```

Result:

- Train: 8,591 positive images / 9,004 mosquito boxes + 10,228 negative-only images.
- Val: 1,955 positive images / 2,020 mosquito boxes + 1,772 negative-only images.

Recommended Stage 2 classifier crops:

```bash
python3 training/build_classifier_crops_from_detector.py \
  --dataset-dir data/processed/real_detector_mix_hardneg_balanced_coco \
  --output-dir data/classifier/real_detector_crops_hardneg_balanced \
  --manifest artifacts/classifier_real_detector_crops_hardneg_balanced/manifest.csv \
  --negative-per-image 1 \
  --padding-ratio 2.2 \
  --seed 20260628 \
  --clean
```

Result:

- 11,024 mosquito ROI crops.
- 46,546 hard-negative ROI crops.
- 57,570 total crops.

## Next Data Priorities

1. Download/license-check indoor hard negatives: walls, ceilings, curtains, stains, dust, reflections, low-light blur.
2. Download/license-check non-mosquito insect negatives: flies, moths, spiders, beetles, small wall insects.
3. Export real app false positives from `MosquitoFinderReview/candidate_hard_negative` and ingest them with `build_hard_negative_coco.py`.
4. Use D-FINE/YOLOX teacher predictions on Mosquito Alert only for annotation queues; keep reviewed boxes separate from pure pseudo labels.
