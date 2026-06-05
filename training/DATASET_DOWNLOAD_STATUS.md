# Dataset Download Status

Updated: 2026-06-06 04:28 CST

## Active Downloads

### Mosquito Alert Tigapics

- Source: https://labs.mosquitoalert.com/metadata_public_portal/notebooks/tigapics.html
- License shown in metadata: CC0
- Local metadata:
  - `data/external/mosquito_alert_tigapics/tigapics_metadata.html`
  - `data/external/mosquito_alert_tigapics/labels/File_List.json`
- Total listed images: 40,978
- Total listed raw size: about 47.45 GB
- Local image directory: `data/external/mosquito_alert_tigapics/images/`
- Download runner: tmux session `mosquito_alert_download`
- Current state: running in tmux with higher concurrency to better use available memory and network.
- Current progress: `21400/40978` checked in the current run after restart.
- Current run counts after restart: `downloaded=3592`, `skipped=17808`, `failed=0`.
- Current local size: about 22 GB
- Current local images: about 18,000.
- Recent activity: raised from `--workers 8` to `--workers 12` after the initial post-restart observation showed new downloads progressing with no failures.
- Failure ledger: `data/external/mosquito_alert_tigapics/failed_downloads.jsonl`
- Resume command:

```bash
tmux attach -t mosquito_alert_download
```

or restart:

```bash
python3 training/download_mosquito_alert_tigapics.py --workers 12 --retries 6 --timeout 30 --progress-every 100
```

### Hugging Face Mosquito Species Detection Dataset

- Source: https://huggingface.co/datasets/iloncka/mosquito-species-detection-dataset
- Local directory: `data/external/huggingface_mosquito_species/`
- Current state: downloaded.
- Downloaded files:
  - `data/train-00000-of-00004.parquet`
  - `data/train-00001-of-00004.parquet`
  - `data/train-00002-of-00004.parquet`
  - `data/train-00003-of-00004.parquet`

## Completed Local Clones

### YOLito

- Source: https://github.com/WildMosquit0/YOLito
- Local directory: `data/external/yolito/repo/`
- Includes pretrained `weights/best.pt` and inference/slicing code.

### MosquitoFusion

- Source: https://github.com/faiyazabdullah/MosquitoFusion
- Local directory: `data/external/mosquitofusion/repo/`
- Includes sample prediction images, training/validation results, notebooks, and YOLO weights.

## Completed Downloads

### Kaggle Low Light Mosquito Images

- Source: https://www.kaggle.com/datasets/arjav007/low-light-mosquito-images
- Expected content: 8,025 low-light phone images with bounding boxes and mosquito species labels.
- License shown on Kaggle page: Apache 2.0
- Status: downloaded and unzipped.
- Local directory: `data/external/kaggle_low_light_mosquito/dataset/`
- Local size: about 3.4 GB
- Validation report: `training/KAGGLE_LOW_LIGHT_VALIDATION.md`
- Derived YOLO dataset: `data/processed/kaggle_yolo_single_class/`
- Derived COCO dataset: `data/processed/kaggle_coco_single_class/`
- Derived dataset status: generated; 7,487 valid samples, 3 skipped samples.
- Train images: 7,490
- Train labels: 7,488
- Test images: 525
- Known data issues:
  - 2 train image files share basename `ba5889d4-66f1-4395-ba1a-bc7ebb603f9b` and have no matching label.
  - 1 label has normalized x-center outside `[0, 1]`: `train_dark/labels/train/120b30b0-c7db-4f0a-bead-a30424a65453.txt`.
  - Test split has images but no labels.
- Token file path: `/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.secrets/kaggle/access_token`
- CLI link path: `~/.kaggle/access_token`
- Kaggle CLI path: `/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/kaggle-cli/bin/kaggle`
- Note: the system Python 3.9 Kaggle CLI only supports legacy username/key auth. A Python 3.13 virtualenv CLI (`Kaggle CLI 2.2.1`) was installed because it supports `KGAT_*` access tokens.
- Retry command:

```bash
KAGGLE_API_TOKEN="$(cat /Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.secrets/kaggle/access_token)" \
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/kaggle-cli/bin/kaggle datasets download \
  -d arjav007/low-light-mosquito-images \
  -p data/external/kaggle_low_light_mosquito \
  --unzip
```

## Shared Frameworks

Framework repositories are now kept outside the business project:

```text
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/
├── D-FINE/
└── YOLOX/
```

Note: YOLOX emitted a macOS case-insensitive filename collision warning in the Android demo directory. The Python training code is present, but this should be recorded as a framework checkout caveat.
