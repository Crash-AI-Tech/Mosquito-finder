# YOLOX Combined Dataset Experiment

Generated: 2026-06-06

## Purpose

Test whether adding the Hugging Face mosquito detection dataset to the existing Kaggle detection training improves YOLOX detector quality.

## Combined COCO Dataset

- Script: `training/merge_coco_detection_datasets.py`
- YOLOX exp: `training/yolox_combined_coco_smoke.py`
- Output: `data/processed/combined_mosquito_coco_single_class/`
- Image storage: symlinks

| Split | Images | Boxes | Kaggle images / boxes | Hugging Face images / boxes |
| --- | ---: | ---: | ---: | ---: |
| train | 8591 | 9004 | 5997 / 5997 | 2594 / 3007 |
| val | 1956 | 2021 | 1490 / 1490 | 466 / 531 |

## Training Run

Command shape:

```bash
python training/train_yolox_mps_smoke.py \
  --exp-module training.yolox_combined_coco_smoke \
  --device mps \
  --batch-size 96 \
  --steps 2000 \
  --print-every 100 \
  --checkpoint-every 500 \
  --num-workers 2 \
  --cache-img ram \
  --lr 3e-7 \
  --resume artifacts/yolox_best_current/best.pt \
  --output-dir artifacts/yolox_combined_b96_w2_ram_lr3e7_s2000_resume_best
```

Result:

- Resumed from total step: `17100`
- Completed total step: `19100`
- RAM image cache: about `3.0GB`
- Runtime: `1148.293s`
- Speed: `0.574s/step`
- Final loss: `5.953866`
- Latest checkpoint: `artifacts/yolox_combined_b96_w2_ram_lr3e7_s2000_resume_best/latest.pt`

## Evaluation Summary

IoU threshold: `0.50`

| Model / checkpoint | Eval split | Best F1 | Precision @ best F1 | Recall @ best F1 | High precision point |
| --- | --- | ---: | ---: | ---: | --- |
| Previous best `artifacts/yolox_best_current/best.pt` | Kaggle val | 73.65% | 79.80% | 68.39% | 94.95% precision @ conf 0.70, 12.62% recall |
| Previous best `artifacts/yolox_best_current/best.pt` | Combined val | 61.78% | 79.73% | 50.42% | 94.95% precision @ conf 0.70, 9.30% recall |
| Combined latest `latest.pt` | Kaggle val | 67.54% | 76.16% | 60.67% | 89.55% precision @ conf 0.70, 4.03% recall |
| Combined latest `latest.pt` | Combined val | 57.04% | 70.93% | 47.70% | 100% precision only hits 1 box, not useful |

Intermediate checkpoints on Kaggle val:

| Checkpoint | Best F1 |
| --- | ---: |
| `step_17600.pt` | 59.47% |
| `step_18100.pt` | 64.95% |
| `step_18600.pt` | 67.47% |

## Decision

Do not replace the App YOLOX model with the combined fine-tuned checkpoint.

The existing checkpoint remains better for the current high-precision App preset. The combined run improved neither the original Kaggle validation F1 nor the high-precision operating point.

## Likely Cause

The Hugging Face dataset changes the validation distribution and may have different box style, object scale, or annotation semantics. A simple low-learning-rate continuation run blends the distributions but does not preserve the high-precision operating point.

## Next Step

Before another full run:

1. Visualize Hugging Face annotations and model predictions.
2. Check box semantics, scale distribution, and label noise.
3. Try a lower-risk training recipe:
   - freeze backbone for a short head-only adaptation, or
   - mix Kaggle/Hugging Face with controlled sampling weights, or
   - train on Hugging Face separately and compare transfer behavior.
4. Keep Mosquito Alert as image-level classification / candidate annotation data until bounding boxes are produced.
