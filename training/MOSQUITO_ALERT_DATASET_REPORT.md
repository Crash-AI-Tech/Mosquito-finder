# Mosquito Alert Tigapics Preparation Report

Generated: 2026-06-06

## Source

- Dataset: Mosquito Alert Tigapics / BioStudies `S-BIAD249`
- Local source: `data/external/mosquito_alert_tigapics/`
- Metadata: `data/external/mosquito_alert_tigapics/labels/File_List.json`
- Download command: `training/download_mosquito_alert_tigapics.py`

## Download Status

- Metadata items: `40978`
- Completed main download: `40978/40978`
- Retry result: `2` previously failed files recovered
- Remaining missing file: `1`
  - `Culex/c854ef6b-4419-45d6-b7c8-54d911a51a1a.jpg`
  - Server repeatedly returned `4096` bytes instead of expected `2321708` bytes.
- Local source size: about `49G`

## Prepared Dataset

- Script: `training/prepare_mosquito_alert_species_dataset.py`
- Output: `data/processed/mosquito_alert_species_classification/`
- Output format: ImageFolder-style directory plus `manifest.csv`, `classes.json`, and `summary.json`
- Image storage: symlinks to the source images, avoiding a second 49G copy

## Prepared Counts

- Usable images: `40842`
- Skipped records: `136`
  - Invalid image payloads: `133`
  - Unsupported extensions: `2`
  - Missing file: `1`

## Split Counts

- Train: `34718`
- Val: `6124`

## Class Counts

| Class | Images |
| --- | ---: |
| `aedes_albopictus` | 15598 |
| `other_species` | 11936 |
| `not_sure` | 6681 |
| `culex_sp.` | 6291 |
| `aedes_japonicus` | 166 |
| `aedes_aegypti` | 75 |
| `complex` | 51 |
| `aedes_koreicus` | 39 |
| `japonicus_koreicus` | 5 |

## Important Modeling Note

This dataset has image-level species labels only. It does not contain bounding boxes.

Use it for:

- Species classification experiments
- Real-world image distribution analysis
- Candidate data for manual/assisted annotation
- Possible hard-negative mining after visual verification

Do not directly use it as positive YOLOX/D-FINE detection data unless bounding boxes are produced first. Creating fake full-image boxes would teach the detector that the entire phone photo is the mosquito, which would hurt localization.

## Recommended Next Step

Use the prepared classification split to inspect and cluster real-world samples, then create a small verified bbox subset for detector fine-tuning. Keep YOLOX/D-FINE positive training on real COCO-style bounding boxes from Kaggle and Hugging Face until Mosquito Alert boxes are available.
