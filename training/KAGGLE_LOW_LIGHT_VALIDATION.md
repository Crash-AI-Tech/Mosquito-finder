# Kaggle Low Light Validation

Updated: 2026-06-05

## Summary

- Dataset directory: `/Users/nsaviour/AgentTeam/workplace/codeProject/Crash-AI-Tech/Mosquito-finder/data/external/kaggle_low_light_mosquito/dataset`
- Train images: 7490
- Train labels: 7488
- Test images: 525
- Test labels: 0
- Total train boxes: 7488
- Class IDs: {0: 35, 1: 3330, 2: 59, 3: 3306, 4: 458, 5: 300}

## Findings

- Missing train labels: 2 image files across 1 basename(s).
- Orphan train labels: 0 file(s).
- Duplicate train image basenames: 1.
- Duplicate train label basenames: 0.
- YOLO label format errors: 1.
- Test split has labels: no.

## Missing Train Labels

- `train_dark/images/train/ba5889d4-66f1-4395-ba1a-bc7ebb603f9b.jpeg`
- `train_dark/images/val/ba5889d4-66f1-4395-ba1a-bc7ebb603f9b.jpeg`

## Duplicate Train Image Basenames

- `train_dark/images/train/ba5889d4-66f1-4395-ba1a-bc7ebb603f9b.jpeg`
- `train_dark/images/val/ba5889d4-66f1-4395-ba1a-bc7ebb603f9b.jpeg`

## Label Format Errors

- `/Users/nsaviour/AgentTeam/workplace/codeProject/Crash-AI-Tech/Mosquito-finder/data/external/kaggle_low_light_mosquito/dataset/train_dark/labels/train/120b30b0-c7db-4f0a-bead-a30424a65453.txt:1: normalized box value outside [0, 1]`
