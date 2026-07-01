# Training Run 2026-06-28

## Inputs

- Detector positive data: `data/processed/combined_mosquito_coco_single_class`
- Balanced hard-negative COCO: `data/processed/hard_negative_coco_balanced`
- Mixed detector data: `data/processed/real_detector_mix_hardneg_balanced_coco`
- Stage 2 crops: `artifacts/classifier_real_detector_crops_hardneg_balanced/manifest.csv`

## MosquitoClassifier

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_cnn_classifier_coreml.py \
  --manifest artifacts/classifier_real_detector_crops_hardneg_balanced/manifest.csv \
  --output-dir artifacts/retrain_real/classifier_cnn_real_hardneg_balanced_b2048_e32 \
  --batch-size 2048 \
  --num-workers 4 \
  --epochs 32 \
  --device mps \
  --selection-min-precision 0.97 \
  --thresholds 0.30,0.40,0.50,0.60,0.70,0.80,0.90,0.95,0.97,0.99 \
  --export-coreml \
  --coreml-output artifacts/retrain_real/classifier_cnn_real_hardneg_balanced_b2048_e32/MosquitoClassifierCNN.mlmodel
```

Result:

- Train samples: 48,279
- Eval samples: 9,291
- Best epoch: 27
- Best F1 threshold: 0.40
- Accuracy: 98.98%
- Precision: 97.91%
- Recall: 97.38%
- F1: 97.64%
- High precision threshold 0.97: precision 99.71%, recall 85.35%
- High precision threshold 0.99: precision 99.88%, recall 79.41%

Action:

- Replaced `Mosquito-finder/MosquitoClassifier.mlmodel`.
- `xcodebuild ... CODE_SIGNING_ALLOWED=NO build` passed.

## YOLOX

### Hard-Negative Fine-Tune

Output:

- `artifacts/retrain_real/yolox_real_hardneg_balanced_b96_w2_ram_s3000_resume_best`

Result on mixed hard-negative val:

- Latest best F1: 55.24%
- Precision: 68.04%
- Recall: 46.49%
- Baseline old best on same val: F1 61.86%, precision 79.81%, recall 50.50%

Decision:

- Do not adopt.
- Cause: hard-negative inputs were mostly 64x64 ROI crops. They are useful for Stage 2 classifier, but they are the wrong scale distribution for full-frame detector training.

### Positive-Only Combined Fine-Tune

Output:

- `artifacts/retrain_real/yolox_combined_real_positive_b96_w2_ram_s1200_resume_best`

Result on combined positive val:

- Latest best F1: 56.73%
- Best intermediate `step_17900`: F1 55.09%
- Baseline old best on same val: F1 61.87%

Decision:

- Do not replace `Mosquito-finder/YoloxMosquitoDetector.mlmodel`.
- Keep `artifacts/yolox_best_current/best.pt` as the selected YOLOX checkpoint.

## D-FINE

Smoke:

- `artifacts/retrain_real/dfine_real_hardneg_balanced_mps_smoke_s30`
- MPS + CPU fallback succeeded.

Fine-tune:

```bash
env PYTORCH_ENABLE_MPS_FALLBACK=1 \
  /Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/train_dfine_cpu_smoke.py \
  --config training/dfine_combined_coco_cpu.yml \
  --steps 1000 \
  --lr 1e-6 \
  --device mps \
  --batch-size 16 \
  --num-workers 0 \
  --mps-friendly-integral \
  --resume artifacts/retrain_real/dfine_combined_pseudo_t050_s055_mpsfallback_b16_lr1e6_s1000_resume_latest_fixed_exif/latest.pth \
  --print-every 50 \
  --checkpoint-every 250 \
  --output-dir artifacts/retrain_real/dfine_combined_real_mpsfallback_b16_lr1e6_s1000_resume_pseudo_latest
```

Result:

- Resumed from total step 2,000.
- Completed to total step 3,000.
- Exported CoreML: `artifacts/retrain_real/dfine_combined_real_mpsfallback_b16_lr1e6_s1000_resume_pseudo_latest/DfineMosquitoDetector_latest.mlpackage`

Combined positive val:

- Best F1: 59.43%
- Precision: 71.65%
- Recall: 50.77%

Mixed hard-negative val:

- Best F1: 56.89%
- Precision: 72.11%
- Recall: 46.98%

Decision:

- Candidate improved slightly versus the previous D-FINE record, but not enough to replace the bundled detector without phone testing.

## App Build

After replacing `MosquitoClassifier.mlmodel`, the iOS build passed:

```bash
xcodebuild -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -destination generic/platform=iOS \
  -derivedDataPath /tmp/MosquitoFinderDerivedData \
  CODE_SIGNING_ALLOWED=NO build
```

## Next Actions

1. Phone-test the app with the new Stage 2 classifier and stabilized guidance.
2. Collect app false positives via review export and ingest them into the classifier hard-negative set.
3. For detector hard negatives, collect full-frame phone images, not 64x64 ROI crops.
4. Keep YOLOX unchanged until full-frame detector negatives are available.
5. A/B test the new D-FINE CoreML package manually before replacing the bundled detector.
