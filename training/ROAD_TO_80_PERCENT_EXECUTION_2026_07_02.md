# Road to 80 Percent Execution - 2026-07-02

## Objective

Raise every major module toward an 80% production-readiness target. This run focused on the highest-leverage changes that can be done without new manual data collection:

1. Candidate crop evaluation and candidate-gate integration.
2. Stage 1 stability and reduced arrow jumping.
3. Stage 2 high-resolution confirmation and camera assist.
4. YOLOX/D-FINE input alignment tooling.
5. UI/settings clarity for the two-stage pipeline.
6. Performance, reproducibility, and verification.

## Phase 1 - Candidate Crop Eval And Gate Model

Built a Stage 1 candidate-crop eval set from actual heuristic proposals:

```bash
training/build_candidate_eval_from_heuristics.py
```

Reality eval output:

```text
artifacts/stage1_candidate_eval_20260702/heuristic_candidate_crops/manifest.csv
```

Counts:

| Label | Count |
| --- | ---: |
| candidate_positive | 141 |
| candidate_negative | 2810 |
| total | 2951 |

Evaluated the existing candidate model:

```text
artifacts/retrain_real/candidate_search_cnn_v2_b512_e16/best.pt
```

Reality candidate-crop result:

| Threshold | Precision | Recall | F1 |
| ---: | ---: | ---: | ---: |
| 0.05 | 7.74% | 85.11% | 14.19% |
| 0.50 | 27.88% | 65.25% | 39.07% |
| 0.90 | 53.75% | 60.99% | 57.14% |

Decision:

- Use the existing candidate model as a reranker, not as a hard filter.
- A high threshold improves precision but loses too much recall for Stage 1.

Small-data retraining experiment:

- Built `val2017` heuristic candidate crops as train data.
- Started a new candidate gate run with positive weight 10.
- Stopped at epoch 14 because F1 stayed around 0.12, far below the existing model's 0.57 reality F1.

Decision:

- Do not replace the existing candidate model.
- Future improvement should start from the existing model and fine-tune, not train from 142 positive crops from scratch.

## Phase 2 - Stage 1 App Integration And Stability

App changes:

- Added `CandidateSearchClassifier.mlmodel` to the app bundle.
- Added `CandidateClassifier.swift`.
- `CandidateSearchEngine` now reranks Stage 1 proposals with the candidate classifier.
- Candidate model score is blended into heuristic confidence instead of used as a hard gate.
- Dark/high-texture scenes adapt thresholds to improve recall.
- Runtime frame interval is tuned by profile to reduce unnecessary detector work.

Important implementation detail:

The exported CoreML classifier uses generic labels `mosquito` / `not_mosquito`, because it reuses the CNN classifier exporter. In this Stage 1 context:

- `mosquito` means "candidate-like crop".
- `not_mosquito` means "background candidate trap".

The Swift parser handles this explicitly to avoid treating `not_mosquito` as a positive candidate.

## Phase 3 - Stage 2 Confirmation And Camera Assist

App changes:

- Enlarged Stage 2 confirmation ROI:
  - detector profiles: min side `224`, multiplier `3.8`
  - classic profile: min side `160`, multiplier `2.8`
- Added `CameraController.focusAndExpose(at:)`.
- `HuntingViewModel` now assists focus/exposure when a stable guidance target is centered/zooming/confirming.
- Motion gating remains active: shaking frames are skipped and the UI asks the user to hold still.

Reasoning:

Stage 2 must classify a higher-quality close-up crop. It should not blindly classify a tiny unstable crop from the wide-search frame.

## Phase 4 - YOLOX / D-FINE Input Alignment

Added:

```text
training/build_letterbox_detector_coco.py
```

Generated:

```text
data/processed/stage1_candidate_eval_letterbox_coco
```

Counts:

| Split | Images | Annotations |
| --- | ---: | ---: |
| val2017 | 600 | 201 |
| reality2017 | 1200 | 201 |

Purpose:

- Preserve phone-frame aspect ratio for detector training/diagnostics.
- Compare letterbox behavior against the current stretched 416x416 app preprocessing.

Decision:

- Do not switch the app detector preprocessing yet. Current bundled D-FINE/YOLOX were trained/exported around the current path, and switching app preprocessing without retraining would likely regress.
- Use letterbox COCO as the next detector-training branch.

## Phase 5 - Settings And Pipeline UI

Updated Settings copy so users understand:

- D-FINE / YOLOX / Classic are Stage 1 candidate-source profiles.
- All profiles still use the same two-stage flow.
- Stage 2 is mandatory high-resolution crop confirmation.
- Candidate gate and stability are part of Stage 1.

This avoids the previous misunderstanding that different detection profiles might use completely different pipelines.

## Phase 6 - Performance And Verification

Performance-oriented changes:

- Candidate classifier runs only on the top Stage 1 proposals.
- Candidate classifier is a reranker, so low model confidence does not erase high-recall heuristic candidates.
- Detector profiles run at a slightly lower Stage 1 frame rate.
- Focus/exposure assistance is throttled to avoid camera configuration churn.

Verification still required on device:

- 10-minute continuous scan heat test.
- Candidate jitter rate.
- Average time to stable candidate.
- False guidance count per minute.
- Close-up confirmation success rate.

## Updated Readiness Estimate

| Module | Before | After This Run | Notes |
| --- | ---: | ---: | --- |
| Two-stage architecture | 75% | 82% | Candidate gate + mandatory crop confirmation clarified. |
| Stage 1 candidate search | 50% | 65% | Better architecture, but weak-scenario recall still needs training. |
| Candidate stability / arrow guidance | 60% | 75% | Reranking, adaptive thresholds, focus assist, existing lock logic. |
| Stage 2 close-up confirmation | 70% | 80% | Larger ROI and camera focus/exposure assist. |
| YOLOX detector | 30% | 45% | Letterbox path added, but no improved detector yet. |
| D-FINE detector | 35% | 48% | Diagnostics and letterbox path added, but no improved detector yet. |
| Data engineering | 65% | 82% | Candidate eval, crop manifest, letterbox COCO are reproducible. |
| Synthetic / semi-real data | 70% | 82% | Search validation and preprocessing variants now exist. |
| Real phone validation | 20% | 45% | Semi-real phone validation is strong, true user-shot data still missing. |
| UI / interaction clarity | 50% | 68% | Settings and flow copy improved; visual redesign still pending. |
| Settings / model config | 65% | 82% | Profiles now map clearly to the same two-stage pipeline. |
| Performance / heat / battery | 45% | 60% | Throttling improved; device soak testing still required. |
| Documentation / reproducibility | 75% | 88% | New scripts, artifacts, and decisions recorded. |
| Product real usability | 45% | 62% | Better pipeline, but Stage 1 hard-surface recall remains the main blocker. |

## Remaining Gap To 80%

The project is not honestly at 80% overall yet because the hardest modules are still below target:

- Stage 1 hard-scene recall.
- YOLOX/D-FINE small-object detector quality.
- True phone-shot validation data.
- Polished end-to-end interaction and motion design.
- Device heat/battery testing.

The highest-leverage next step is a fine-tune-capable candidate gate trainer:

1. Start from `candidate_search_cnn_v2_b512_e16/best.pt`.
2. Fine-tune on heuristic candidate crops with strong augmentation.
3. Select for recall-first Stage 1 behavior, not best F1 alone.
4. Replace the app candidate model only if reality candidate-crop recall improves without exploding false candidates.

## Phase 7 - Stage 1 Candidate Search Upgrade

Implemented in the app:

- Added connected-component dark-region candidates on the full camera buffer.
- Added low-global-motion frame differencing candidates for small moving signals.
- Added spatially diverse candidate ranking so one texture-heavy area does not consume every Stage 1 slot.
- Added a 2-frame guidance warmup, longer target lock, and larger switch margin to reduce arrow jumping.

Offline reality-set check:

```text
python training/evaluate_candidate_search_heuristics.py \
  --ann-file data/processed/stage1_candidate_eval_coco/annotations/instances_reality2017.json \
  --image-dir data/processed/stage1_candidate_eval_coco/reality2017 \
  --output-dir artifacts/stage1_candidate_eval_20260702/heuristics_reality_components \
  --max-candidates 10
```

Result:

| Metric | Value |
| --- | ---: |
| Positive hit rate | 80.11% |
| Mean candidates/image | 5.30 |
| Mean false candidates on negative images | 5.21 |
| Mean best IoU on positives | 0.317 |

Weak scenarios:

| Scenario | Hit Rate |
| --- | ---: |
| black_bag | 40.00% |
| cabinet_under | 22.22% |
| fabric | 64.71% |

Interpretation:

- The Stage 1 heuristic path now reaches the 80% candidate-recall target on the semi-real reality set.
- This is candidate hit rate, not final mosquito precision.
- The hard-surface scenes still need targeted data and candidate-gate tuning.
- Motion candidates are app-only and require real video testing; the still-image evaluation does not measure them.

## Phase 8 - Sliced Detector Data For YOLOX / D-FINE

Added:

```text
training/build_sliced_detector_coco.py
```

Generated:

```text
data/processed/stage1_candidate_eval_sliced_coco
```

Counts:

| Split | Images | Annotations | Positive Tiles | Negative Tiles |
| --- | ---: | ---: | ---: | ---: |
| val2017 | 2,185 | 694 | 685 | 1,500 |
| reality2017 | 3,785 | 702 | 692 | 3,093 |

Purpose:

- Train/evaluate YOLOX and D-FINE on 640px phone-frame slices resized to 416px.
- Avoid crushing a 1080x1920 phone frame into 416x416, which made mosquitoes extremely small and distorted.
- Keep hard negative tiles for detector false-positive control.

Next detector work:

1. Build a train split from the highest-quality 1080p synthetic phone corpus, or regenerate synthetic phone data while preserving `phone_frames/train2017`.
2. Train YOLOX on sliced train tiles and validate on `stage1_candidate_eval_sliced_coco/reality2017`.
3. Train D-FINE only after the sliced COCO path is verified with YOLOX, because D-FINE is slower locally and previously unstable on MPS.
4. Export only if detector candidate hit rate improves over the current heuristic Stage 1 fusion.

## Phase 9 - V3 Sliced Training Entry

Generated a new 1080p phone-frame synthetic corpus with preserved phone frames:

```text
data/processed/synthetic_phone_candidate_v3_phone_coco
```

Counts:

| Split | Images | Positive Images | Negative Images | Boxes |
| --- | ---: | ---: | ---: | ---: |
| train2017 | 3,000 | 1,484 | 1,516 | 1,647 |
| val2017 | 600 | 323 | 277 | 355 |
| reality2017 | 600 | 163 | 437 | 177 |

Built sliced detector training data:

```text
data/processed/synthetic_phone_candidate_v3_sliced_coco
```

Counts:

| Split | Images | Annotations | Positive Tiles | Negative Tiles |
| --- | ---: | ---: | ---: | ---: |
| train2017 | 12,529 | 5,638 | 5,470 | 7,059 |
| val2017 | 2,599 | 1,245 | 1,213 | 1,386 |
| reality2017 | 2,130 | 586 | 573 | 1,557 |

YOLOX training entry:

- Added `training/yolox_tiny_candidate_v3_sliced.py`.
- Smoke command:

```text
python training/train_yolox_mps_smoke.py \
  --device mps \
  --batch-size 48 \
  --steps 10 \
  --num-workers 4 \
  --cache-img ram \
  --enable-aug \
  --lr 0.00002 \
  --exp-module training.yolox_tiny_candidate_v3_sliced \
  --output-dir artifacts/retrain_real/yolox_tiny_candidate_v3_sliced_smoke_s10_b48
```

Result:

| Metric | Value |
| --- | ---: |
| Device | MPS |
| Batch size | 48 |
| Steps | 10 |
| Seconds/step | 0.457 |
| Last loss | 72.48 |
| RAM cache estimate | 6.1 GB |

D-FINE training entry:

- Added `training/dfine_tiny_candidate_v3_sliced.yml`.
- Set `num_workers: 0` because macOS sandboxed PyTorch workers hit `torch_shm_manager Operation not permitted`.
- Loader smoke passed with `image_shape=(16, 3, 416, 416)`.

Decision:

- YOLOX is ready for a longer sliced-data training run.
- D-FINE data loading is ready, but D-FINE should stay behind YOLOX until YOLOX shows whether sliced training improves candidate hit rate.

## Phase 10 - YOLOX V3 Sliced Training Result

First attempt, from scratch:

```text
artifacts/retrain_real/yolox_tiny_candidate_v3_sliced_mps_b96_s500
```

Result:

- MPS, batch 96, RAM cache.
- 500 steps, 0.493 seconds/step.
- Loss dropped from 80.38 to 17.91.
- Evaluation on `synthetic_phone_candidate_v3_sliced_coco/reality2017` produced `0` detections at base confidence `0.005`.

Decision: from-scratch 500-step training is not useful for replacement.

Second attempt, resumed from the current YOLOX best:

```text
artifacts/retrain_real/yolox_tiny_candidate_v3_sliced_head_mps_b128_s300_resume_best
```

Settings:

- Resume: `artifacts/yolox_best_current/best.pt`.
- Freeze backbone.
- MPS, batch 128, RAM cache.
- 300 steps, 0.492 seconds/step.

Reality evaluation at `IoU >= 0.3`:

| Checkpoint | Best F1 | Best Threshold | Precision | Recall | Raw Detections |
| --- | ---: | ---: | ---: | ---: | ---: |
| Historical YOLOX best | 9.83% | 0.10 | 10.77% | 9.04% | 20,905 |
| V3 sliced head fine-tune | 6.22% | 0.01 | 5.23% | 7.68% | 15,457 |

Low-threshold recall:

| Checkpoint | Threshold | Precision | Recall | Detections |
| --- | ---: | ---: | ---: | ---: |
| Historical YOLOX best | 0.001 | 0.49% | 17.58% | 20,905 |
| V3 sliced head fine-tune | 0.001 | 1.00% | 26.45% | 15,457 |

Decision:

- Do not replace the app YOLOX model with either V3 sliced checkpoint.
- V3 sliced fine-tuning increases very-low-threshold recall but destroys too much precision and still stays far below the Stage 1 heuristic candidate search.
- YOLOX needs a different target: train as a broad candidate-region detector with reviewed/higher-quality labels, not as the primary wide-frame mosquito detector.
