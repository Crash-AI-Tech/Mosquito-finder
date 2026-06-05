# YOLOX Precision Report

Updated: 2026-06-06 05:15 CST

## Goal

Train a YOLOX mosquito detector for the iOS app with validation precision at or above 95%, then export the selected model to Core ML and install it in the app.

## Current Result

The 95% validation precision target has not been reached yet.

Selected checkpoint for app testing:

```text
artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/step_17100.pt
```

Exported app model:

```text
Mosquito-finder/YoloxMosquitoDetector.mlmodel
```

Validation set:

- Dataset: `data/processed/kaggle_coco_single_class/val2017`
- Images: 1,490
- Ground-truth boxes: 1,490
- IoU threshold: 0.50

Best F1 operating point:

| Confidence | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| 0.40 | 79.80% | 68.39% | 73.65% |

Closest high-precision operating point:

| Confidence | Precision | Recall | TP | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.70 | 94.95% | 12.62% | 188 | 10 | 1302 |

Decision:

- Use threshold `0.70` in the YOLOX high-precision app preset for local device testing.
- Do not claim the 95% target is complete yet.
- Continue improving the dataset mix and hard-negative calibration before treating this model as production-ready.

## Training Run

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_yolox_mps_smoke.py \
  --device mps \
  --batch-size 96 \
  --num-workers 2 \
  --cache-img ram \
  --steps 1200 \
  --print-every 100 \
  --checkpoint-every 300 \
  --lr 3e-7 \
  --resume artifacts/yolox_best_current/best.pt \
  --output-dir artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best
```

Timing:

- 1,200 steps
- 677.179 seconds total
- 0.564 seconds per step
- RAM image cache: about 2.2 GB

## Evaluation Command

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/evaluate_yolox_detector.py \
  --checkpoint artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/step_17100.pt \
  --output-json artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/eval_step_17100.json
```

Fine threshold check near 95%:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/evaluate_yolox_detector.py \
  --checkpoint artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/step_17100.pt \
  --thresholds 0.690,0.695,0.700,0.705,0.710,0.715,0.720,0.725,0.730 \
  --output-json artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/eval_step_17100_fine.json
```

## Core ML Export

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/export_yolox_coreml.py \
  --checkpoint artifacts/yolox_best_current/best.pt \
  --output Mosquito-finder/YoloxMosquitoDetector.mlmodel \
  --image-size 416
```

## App Integration

The app now routes `ModelMode.detectorYolox` through the full-frame detector path in `Stage1Detector`.

YOLOX output parsing expects:

```text
[x1, y1, x2, y2, objectness, class_confidence]
```

Post-processing:

- Confidence = `objectness * class_confidence`
- Coordinates are scaled from 416x416 model space to the original frame.
- NMS IoU threshold: `0.45`
- YOLOX high-precision preset threshold: `0.70`

Build verification:

```bash
xcodebuild \
  -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Result: build succeeded.

## Next Improvement Path

To push precision above 95% without making recall unusable:

1. Finish Mosquito Alert download and add a real-data validation split.
2. Add hard-negative home-scene images to reduce false positives around dark spots and textured backgrounds.
3. Re-train YOLOX with the combined Kaggle + Mosquito Alert dataset.
4. Re-calibrate confidence thresholds from the full validation curve.
5. Re-export Core ML only after validation precision exceeds 95%.
