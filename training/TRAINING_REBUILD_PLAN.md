# Mosquito Finder Training Rebuild Plan

Updated: 2026-06-06

## Workspace Layout

Shared training framework repositories live outside business projects:

```text
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/
├── YOLOX/
├── D-FINE/
└── ...
```

Each business project keeps only its own training assets:

```text
Mosquito-finder/
├── training/      # project configs, export scripts, conversion scripts
├── data/          # project datasets, ignored by Git
├── artifacts/     # checkpoints, metrics, exported intermediate files, ignored by Git
└── Mosquito-finder/
    ├── MosquitoClassifier.mlmodel
    ├── YoloxMosquitoDetector.mlmodel
    └── DfineMosquitoDetector.mlpackage
```

## Runtime Detection Design

The app should expose two configurable stages in Settings:

1. Stage 1: lightweight candidate detection.
   - Purpose: find possible regions quickly and draw yellow guidance boxes.
   - Candidate models: lightweight detector, D-FINE/YOLOX nano variants, or traditional dark-spot scan as fallback.
   - Parameters: candidate threshold, max candidates, stable frames, scan interval, region size filters.

2. Stage 2: heavier precision verification.
   - Purpose: confirm whether the candidate is a mosquito.
   - Candidate models: D-FINE, YOLOX, MosquitoClassifier ROI classifier.
   - Parameters: confidence threshold, center/zoom requirements, cooldown, precision presets.

CoreML Strict and CoreML Balanced are parameter presets for the same `MosquitoClassifier.mlmodel`, not separate model choices.

## Model Roles

- `MosquitoClassifier.mlmodel`
  - Best role: Stage 2 ROI fallback.
  - Goal: train with real detector crops and hard negatives.

- `YoloxMosquitoDetector.mlmodel`
  - Best role: lightweight or backup detector after real-data retraining.
  - Goal: compare against D-FINE on the same real dataset and device budget.

- `DfineMosquitoDetector.mlpackage`
  - Best role: current primary full-frame detector.
  - Goal: retrain with real data first, then calibrate thresholds for home environments.

## Data Priority

1. Real mosquito datasets with boxes or usable labels.
2. Real home-environment hard negatives.
3. AI-generated home-scene images, paused for now.
4. Code-generated synthetic edge cases, only as low-ratio supplement.

AI 25-grid generation is deferred until real datasets are downloaded and assessed.

## Current Execution Notes

- Kaggle low-light data is downloaded and validated in `training/KAGGLE_LOW_LIGHT_VALIDATION.md`.
- Kaggle can now feed the first real-data detector sanity check after excluding the known duplicate/unlabeled image and the single malformed label row.
- Mosquito Alert download is still useful but unreliable from the remote server. The downloader now records final failures to `failed_downloads.jsonl` and runs lower concurrency to reduce stalls.
- Do not block Kaggle inspection or baseline retraining on the full Mosquito Alert download.

## Derived Training Data Policy

- Keep `data/external/` as read-only raw data. Do not modify downloaded dataset structure.
- Write model-specific derived data under `data/processed/`.
- Each derived dataset must include a machine-readable summary that records source paths, class mapping, skipped samples, and split counts.

Current derived datasets:

```text
data/processed/
├── kaggle_yolo_single_class/   # YOLO txt layout for generic YOLO tooling.
└── kaggle_coco_single_class/   # COCO train2017/val2017 layout for D-FINE and YOLOX smoke runs.
```

Kaggle single-class mapping:

- All original species class IDs are mapped to class `0: mosquito`.
- The first detector smoke run is intentionally single-class. Species-level modeling can be revisited after the detection pipeline is stable.
- Skipped samples are listed in each derived dataset's `summary.json`.

Smoke configs:

- D-FINE: `training/dfine_kaggle_smoke.yml`
- YOLOX: `training/yolox_kaggle_smoke.py`

Environment note:

- Shared training virtualenv: `/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train`
- Package manager: `uv`; Python: 3.11.11; virtualenv size after minimal dependencies is about 888 MB.
- Minimal smoke dependencies are recorded in `training/requirements-smoke.txt`.
- YOLOX dataset loader check passes against `data/processed/kaggle_coco_single_class` with 5,997 training samples.
- YOLOX one-batch CPU forward/backward smoke check passes via `training/smoke_yolox_forward.py`.
- YOLOX MPS forward/backward now passes after local MPS compatibility patches in the shared YOLOX framework.
- YOLOX limited-step local trainer: `training/train_yolox_mps_smoke.py`.
- YOLOX local trainer writes checkpoints and `summary.json` under `artifacts/`.
- Local timing on M4 Max:
  - batch 2, 5 steps: MPS `0.751s/step`, CPU `0.104s/step`; CPU is faster because tiny batches do not amortize MPS dispatch overhead.
  - batch 8, 10 steps: MPS `0.299s/step`, CPU `0.301s/step`; roughly tied.
  - batch 16, 10 steps: MPS `0.390s/step`, CPU `1.386s/step`; MPS is about 3.5x faster.
- YOLOX MPS stability checks:
  - batch 16, 100 steps: last loss `36.4549`, `25.903s` elapsed, `0.259s/step`, checkpoint `artifacts/yolox_mps_smoke_b16_s100/latest.pt`.
  - batch 16, 400 steps: last loss `20.7858`, `100.298s` elapsed, `0.251s/step`, checkpoint `artifacts/yolox_mps_smoke_b16_s400/latest.pt`.
  - batch 16, 1,200 steps: last loss `10.3811`, `296.862s` elapsed, `0.247s/step`, checkpoint `artifacts/yolox_mps_baseline_b16_s1200/latest.pt`.
- Local M4 Max memory note: this Mac has 128 GB unified memory and PyTorch reports MPS available. `torch.mps.recommended_max_memory()` is about 115 GB, so local GPU training should use larger batches plus RAM caching when stable.
- YOLOX throughput tuning on the Kaggle-derived train set:
  - batch 16, workers 0, no image cache: about `60 img/s`.
  - batch 64/96/128, workers 0, no image cache: about `66 img/s`; larger batch alone does not remove the bottleneck.
  - batch 96, workers 2, no image cache: about `150 img/s`.
  - batch 96, workers 2, RAM image cache: about `161 img/s`, using about `2.1 GB` RAM for cached images.
- Recommended local YOLOX fast training baseline: `--device mps --batch-size 96 --num-workers 2 --cache-img ram`.
- Current selected YOLOX MPS checkpoint:
  - Stable alias: `artifacts/yolox_best_current/best.pt`.
  - Source checkpoint: `artifacts/yolox_precision_b96_w2_ram_lr3e7_s1200_resume_best/step_17100.pt`.
  - Full validation report: `training/YOLOX_PRECISION_REPORT.md`.
  - Best F1 point on 1,490 validation images: confidence `0.40`, precision `79.80%`, recall `68.39%`, F1 `73.65%`.
  - Closest high-precision point: confidence `0.70`, precision `94.95%`, recall `12.62%`, TP `188`, FP `10`, FN `1302`.
  - Decision: export this checkpoint to the app for local testing, but do not mark the 95% target as complete.
- Fast large-batch fine-tune from the current best:
  - Run directory: `artifacts/yolox_mps_fast_finetune_b96_w2_ram_s900_resume16200/`.
  - Config: `batch-size=96`, `num-workers=2`, `cache-img=ram`, `lr=1e-6`, `900 steps`.
  - Results on the same 300-image validation sample:
    - `step_16500.pt`: mean best IoU `0.5752`, IoU>=0.5 `218/300`, IoU>=0.3 `258/300`.
    - `step_16800.pt`: mean best IoU `0.5767`, IoU>=0.5 `215/300`, IoU>=0.3 `258/300`.
    - `step_17100.pt` / `latest.pt`: mean best IoU `0.5799`, IoU>=0.5 `219/300`, IoU>=0.3 `257/300`.
  - Decision: keep `artifacts/yolox_best_current/best.pt` pointing to `step_16200.pt` because it still has the best IoU>=0.5 count (`221/300`), even though the large-batch run slightly improves mean IoU and confidence.
- Fresh-optimizer large-batch fine-tune:
  - Run directory: `artifacts/yolox_mps_fast_finetune_b96_w2_ram_freshopt_s600_resume16200/`.
  - Config: `batch-size=96`, `num-workers=2`, `cache-img=ram`, `lr=5e-7`, `600 steps`, model weights resumed without optimizer momentum.
  - Timing: `355.203s` for 600 steps, about `0.592s/step`.
  - Results on the same 300-image validation sample:
    - `step_16500.pt`: mean best IoU `0.5725`, IoU>=0.5 `215/300`, IoU>=0.3 `257/300`.
    - `step_16800.pt` / `latest.pt`: mean best IoU `0.5746`, IoU>=0.5 `216/300`, IoU>=0.3 `258/300`.
  - Decision: do not adopt; fresh optimizer with this LR is worse than the current best.
- D-FINE base import, YAML config parse, and one-batch dataloader smoke check pass via `training/smoke_dfine_loader.py`.
- D-FINE MPS model forward currently fails inside MPSGraph with a matmul shape verification error. This is a framework/operator compatibility blocker, not a dataset problem.
- D-FINE CPU training smoke passes via `training/train_dfine_cpu_smoke.py`: 3 steps, last loss `30.3671`, `0.524s/step`, checkpoint `artifacts/dfine_cpu_smoke_s3/latest.pth`.
- Current local training route: use YOLOX on MPS for the first real baseline; keep D-FINE to CPU smoke checks until the MPSGraph issue is isolated or an upstream-compatible D-FINE variant is selected.

## Initial Download Targets

- Kaggle: `arjav007/low-light-mosquito-images`
- Mosquito Alert: Tigapics / BioImage Archive distributions
- GitHub: `WildMosquit0/YOLito`
- GitHub: `faiyazabdullah/MosquitoFusion`
- Hugging Face: `iloncka/mosquito-species-detection-dataset`

All downloaded data stays under `data/external/` and remains ignored by Git.
