# Synthetic Phone Data Training Run - 2026-06-28

## Goal

Improve the two-stage mosquito search pipeline without new manual photo collection by generating realistic phone-view training data, then retraining the three supported models:

- Stage-1 detector: YOLOX
- Stage-1 detector: D-FINE
- Stage-2 classifier: MosquitoClassifier

Only models that improved on real or mixed validation were bundled into the app.

## Synthetic Data

Generator:

```bash
python3 training/build_realistic_synthetic_phone_corpus.py \
  --output-dir data/processed/synthetic_phone_detector_coco \
  --train-count 5000 \
  --val-count 900 \
  --reality-count 900 \
  --positive-ratio 0.48 \
  --reality-positive-ratio 0.22 \
  --seed 20260628 \
  --clean
```

The generator renders 1080x1920 phone frames, then stretches them to 416x416 to match the current `Stage1Detector.resize` behavior. COCO boxes are projected from phone coordinates into the model input coordinates.

Generated split summary:

| Split | Images | Positive Images | Negative Images | Boxes |
| --- | ---: | ---: | ---: | ---: |
| train2017 | 5000 | 2386 | 2614 | 2633 |
| val2017 | 900 | 430 | 470 | 482 |
| reality2017 | 900 | 203 | 697 | 221 |

## Mixed Detector Dataset

Output:

```text
data/processed/real_synthetic_phone_detector_mix_coco
```

Sources:

- Real positives: `data/processed/combined_mosquito_coco_single_class`
- Synthetic positives and negatives: `data/processed/synthetic_phone_detector_coco`
- Existing hard negatives: `data/processed/hard_negative_coco_balanced`

Summary:

| Split | Images | Boxes |
| --- | ---: | ---: |
| train | 23819 | 11637 |
| val | 4627 | 2502 |

Train includes 10228 existing hard-negative images and 2614 synthetic negative-only phone frames.

## MosquitoClassifier

Classifier crop dataset:

```bash
python3 training/build_classifier_crops_from_detector.py \
  --dataset-dir data/processed/real_synthetic_phone_detector_mix_coco \
  --output-dir data/classifier/real_synthetic_phone_crops \
  --manifest artifacts/classifier_real_synthetic_phone_crops/manifest.csv \
  --negative-per-image 1 \
  --padding-ratio 2.2 \
  --max-source-pixels 12000000 \
  --seed 20260628 \
  --clean
```

Crop summary:

- mosquito: 12279
- hardnegative: 56757
- total: 69036

Training:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_cnn_classifier_coreml.py \
  --manifest artifacts/classifier_real_synthetic_phone_crops/manifest.csv \
  --output-dir artifacts/retrain_real/classifier_cnn_real_synthetic_phone_b2048_e24 \
  --epochs 24 \
  --batch-size 2048 \
  --num-workers 4 \
  --torch-threads 12 \
  --device mps \
  --lr 0.0008 \
  --weight-decay 0.0001 \
  --positive-weight 2.5 \
  --negative-weight 1.0 \
  --selection-min-precision 0.97 \
  --thresholds 0.30,0.40,0.50,0.60,0.70,0.80,0.90,0.95,0.97,0.99 \
  --seed 20260628 \
  --export-coreml \
  --coreml-output artifacts/retrain_real/classifier_cnn_real_synthetic_phone_b2048_e24/MosquitoClassifier.mlmodel
```

Mixed eval best:

- best epoch: 22
- threshold 0.60: precision 97.84%, recall 98.53%, F1 98.18%
- threshold 0.97: precision 99.69%, recall 90.47%

Real hard-negative manifest cross-eval:

| Model | Best F1 | Threshold | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Previous bundled classifier | 97.64% | 0.40 | 97.91% | 97.38% |
| Synthetic-phone candidate | 97.94% | 0.40 | 96.94% | 98.96% |

At the app's high threshold region:

| Model | Threshold | Precision | Recall |
| --- | ---: | ---: | ---: |
| Previous bundled classifier | 0.95 | 99.49% | 87.67% |
| Synthetic-phone candidate | 0.95 | 99.52% | 91.93% |

Decision: replaced `Mosquito-finder/MosquitoClassifier.mlmodel`.

## YOLOX

Config:

```text
training/yolox_real_synthetic_phone.py
```

Training:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_yolox_mps_smoke.py \
  --device mps \
  --batch-size 96 \
  --steps 800 \
  --print-every 100 \
  --checkpoint-every 400 \
  --num-workers 2 \
  --cache-img ram \
  --enable-aug \
  --lr 0.00000025 \
  --exp-module training.yolox_real_synthetic_phone \
  --resume artifacts/yolox_best_current/best.pt \
  --output-dir artifacts/retrain_real/yolox_real_synthetic_phone_b96_w2_ram_lr25e8_s800_resume_best
```

Mixed val results:

| Checkpoint | Best F1 | Threshold | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Current bundled best | 53.90% | 0.40 | 79.50% | 40.77% |
| step_17500 | 36.05% | 0.15 | 51.88% | 27.62% |
| latest / step_17900 | 39.71% | 0.15 | 52.82% | 31.81% |

Decision: did not replace YOLOX. Directly mixing synthetic phone frames made YOLOX too conservative and reduced recall.

## D-FINE

Config:

```text
training/dfine_real_synthetic_phone.yml
```

Training:

```bash
env PYTORCH_ENABLE_MPS_FALLBACK=1 \
  /Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_dfine_cpu_smoke.py \
  --config training/dfine_real_synthetic_phone.yml \
  --device mps \
  --mps-friendly-integral \
  --batch-size 16 \
  --num-workers 2 \
  --steps 300 \
  --print-every 50 \
  --checkpoint-every 150 \
  --lr 0.0000006 \
  --resume artifacts/retrain_real/dfine_combined_real_mpsfallback_b16_lr1e6_s1000_resume_pseudo_latest/latest.pth \
  --output-dir artifacts/retrain_real/dfine_real_synthetic_phone_mpsfallback_b16_lr6e7_s300_resume_real_latest
```

CoreML candidate:

```text
artifacts/retrain_real/dfine_real_synthetic_phone_mpsfallback_b16_lr6e7_s300_resume_real_latest/DfineMosquitoDetector_latest.mlpackage
```

Mixed val:

| Model | Best F1 | Threshold | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Previous bundled D-FINE | 0.49% | 0.30 | 1.08% | 0.32% |
| Synthetic-phone candidate | 37.74% | 0.30 | 39.07% | 36.49% |

Combined real val:

| Model | Best F1 | Threshold | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| Previous bundled D-FINE | 0.60% | 0.30 | 1.21% | 0.40% |
| Synthetic-phone candidate | 56.68% | 0.20 | 56.75% | 56.61% |

Decision: replaced `Mosquito-finder/DfineMosquitoDetector.mlpackage`. It is still weaker than YOLOX for the current pipeline, but it is much better than the previously bundled D-FINE model in CoreML evaluation.

## App Build

Validated after replacing classifier and D-FINE:

```bash
xcodebuild -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -destination generic/platform=iOS \
  -derivedDataPath /tmp/MosquitoFinderDerivedData \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Result: `BUILD SUCCEEDED`.

## Next Training Direction

The synthetic data helped Stage-2 classification and D-FINE, but direct YOLOX detector mixing hurt recall. The next YOLOX attempt should avoid full negative-heavy joint training and instead use one of:

- Freeze backbone/FPN and train only the head with a lower negative ratio.
- Train with real positives plus synthetic positives first, then add hard negatives only in a short final precision-tuning phase.
- Use synthetic phone data as validation and threshold calibration rather than a full training source.
- Add model-level temporal stability in the app as a second protection layer instead of forcing detector precision too aggressively.

## Candidate Search V2 Run - 2026-07-01

Goal: change Stage 1 from "mosquito detector" to "candidate search" and rebuild training data around realistic phone search scenes, including fabric, black bags, cabinet undersides, dark spots, local contrast, and near-miss insects.

App-side changes:

- Added `CandidateSearchEngine` for Stage 1 candidate search.
- Fused model detector output with traditional image-processing candidates: dark spots, blobs, local contrast, and small connected regions.
- Added lightweight candidate stability before `ObjectTracker` so guidance arrows are less likely to jump frame-to-frame.
- Updated hunting guidance copy to describe the real flow: search likely areas, lock a stable candidate, move closer, then confirm with Stage 2.

Generated candidate corpus:

```bash
python3 training/build_realistic_synthetic_phone_corpus.py \
  --output-dir data/processed/synthetic_phone_candidate_v2_coco \
  --train-count 2400 \
  --val-count 480 \
  --reality-count 480 \
  --positive-ratio 0.46 \
  --reality-positive-ratio 0.20 \
  --seed 20260701 \
  --clean
```

Split summary:

| Split | Images | Positive Images | Negative Images | Boxes |
| --- | ---: | ---: | ---: | ---: |
| train2017 | 2400 | 1101 | 1299 | 1232 |
| val2017 | 480 | 224 | 256 | 252 |
| reality2017 | 480 | 102 | 378 | 111 |

Candidate crop dataset:

```text
artifacts/candidate_search_v2_crops/manifest.csv
```

Counts:

- candidate: 1595
- background_trap: 17306
- total: 18901

CandidateSearchClassifier training:

```text
artifacts/retrain_real/candidate_search_cnn_v2_b512_e16/CandidateSearchClassifier.mlmodel
```

Synthetic crop validation:

| Threshold | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: |
| 0.60 | 90.00% | 96.43% | 93.10% |
| 0.90 | 95.00% | 90.48% | 92.68% |

Decision: keep as an experimental artifact. It is not bundled yet because it has only synthetic candidate-crop validation, not a real phone-frame validation set.

Stage-2 classifier v2:

```text
artifacts/retrain_real/classifier_cnn_real_candidate_v2_b2048_e20/MosquitoClassifier.mlmodel
```

Cross-eval on the existing real hard-negative manifest:

| Model | Threshold | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| Current/source classifier | 0.40 | 96.94% | 98.96% | 97.94% |
| Candidate v2 classifier | 0.50 | 97.83% | 98.07% | 97.95% |
| Current/source classifier | 0.95 | 99.52% | 91.93% | - |
| Candidate v2 classifier | 0.95 | 99.55% | 87.77% | - |

Decision: do not replace `MosquitoClassifier.mlmodel`. The v2 model is slightly higher at best-F1 operating point but loses recall in the app's high-threshold confirmation range.

YOLOX candidate v2:

```text
artifacts/retrain_real/yolox_tiny_candidate_v2_b64_lr25e8_s400_resume_best/latest.pt
```

Evaluation on `synthetic_phone_candidate_v2_coco/val2017`: current YOLOX and the v2 checkpoint both produced `0` true positives at the tested thresholds. The v2 checkpoint reduced detections but did not recover recall.

Decision: do not replace YOLOX. Before any longer YOLOX run, inspect bbox scale/alignment and synthetic-to-detector preprocessing visually.

D-FINE candidate v2:

```text
artifacts/retrain_real/dfine_tiny_candidate_v2_mpsfallback_b16_lr5e7_s250_resume_current/DfineMosquitoDetector_latest.mlpackage
```

Combined real validation:

| Model | Best Threshold | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: |
| Current App D-FINE | 0.20 | 56.75% | 56.61% | 56.68% |
| Candidate v2 D-FINE | 0.20 | 53.26% | 43.20% | 47.70% |

Decision: do not replace `DfineMosquitoDetector.mlpackage`. Current App D-FINE remains better on real validation.

Build validation after App logic changes:

```bash
xcodebuild -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -destination generic/platform=iOS \
  -derivedDataPath /tmp/MosquitoFinderDerivedData \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Result: `BUILD SUCCEEDED`.

Next direction:

- Integrate `CandidateSearchClassifier.mlmodel` only after building a real or semi-real phone-frame validation set for candidate crops.
- Visualize candidate v2 boxes against YOLOX/D-FINE inputs before more detector training; the `0` TP detector result suggests scale, annotation alignment, or domain mismatch.
- Keep Stage 1 primarily as candidate search plus temporal stability; reserve mosquito confirmation for high-resolution Stage 2 crops.
