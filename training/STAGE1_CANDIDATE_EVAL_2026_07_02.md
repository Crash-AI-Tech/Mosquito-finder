# Stage 1 Candidate Search Evaluation - 2026-07-02

## Goal

Build a reproducible real/semi-real validation path for the new Stage 1 design:

1. Stage 1 searches for candidate areas, not confirmed mosquitoes.
2. Stage 2 confirms mosquito identity from a high-resolution crop.
3. Detector failures should be diagnosed with input/bbox overlays before more training.

## Validation Dataset

Dataset:

```text
data/processed/stage1_candidate_eval_coco
```

Generation command:

```bash
python3 training/build_realistic_synthetic_phone_corpus.py \
  --output-dir data/processed/stage1_candidate_eval_coco \
  --train-count 0 \
  --val-count 600 \
  --reality-count 1200 \
  --positive-ratio 0.28 \
  --reality-positive-ratio 0.16 \
  --seed 20260702 \
  --save-phone-frames \
  --clean
```

Split summary:

| Split | Images | Positive Images | Negative Images | Boxes |
| --- | ---: | ---: | ---: | ---: |
| val2017 | 600 | 184 | 416 | 201 |
| reality2017 | 1200 | 181 | 1019 | 201 |

The `reality2017` split is the Stage 1 candidate validation target. It intentionally has a low positive ratio to approximate real search behavior.

The generator saved both:

- 416x416 detector input frames: `data/processed/stage1_candidate_eval_coco/reality2017`
- 1080x1920 phone frames: `data/processed/stage1_candidate_eval_coco/phone_frames/reality2017`

## New Diagnostic Scripts

Candidate search heuristic evaluation:

```text
training/evaluate_candidate_search_heuristics.py
```

Detector input and bbox alignment diagnostics:

```text
training/diagnose_detector_input_alignment.py
```

D-FINE CoreML evaluation now supports optional overlays:

```bash
training/evaluate_dfine_coreml_detector.py --visualize-dir ...
```

An additional D-FINE-only visualization helper was added:

```text
training/visualize_dfine_coreml_predictions.py
```

## Candidate Search Heuristic Result

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/evaluate_candidate_search_heuristics.py \
  --ann-file data/processed/stage1_candidate_eval_coco/annotations/instances_reality2017.json \
  --image-dir data/processed/stage1_candidate_eval_coco/reality2017 \
  --output-dir artifacts/stage1_candidate_eval_20260702/heuristics_reality \
  --max-candidates 8 \
  --sample-limit 45
```

Output:

```text
artifacts/stage1_candidate_eval_20260702/heuristics_reality
```

Overall:

| Metric | Value |
| --- | ---: |
| Images | 1200 |
| Positive images | 181 |
| Negative images | 1019 |
| Positive candidate hit rate | 53.59% |
| Mean candidates per image | 2.46 |
| Mean false candidates on negative images | 2.41 |
| Mean best IoU on positives | 0.190 |

Weak scenarios:

| Scenario | Positive Hit Rate |
| --- | ---: |
| black_bag | 10.00% |
| cabinet_under | 0.00% |
| fabric | 29.41% |

Interpretation:

- Traditional dark spot/blob/local-contrast search is useful as a low-cost first pass, but it is not enough for hidden mosquitoes on dark bags, cabinet undersides, and fabric.
- The algorithm often locks onto stronger dark artifacts near the true target.
- Stage 1 must stay semantically conservative: "candidate area", not "mosquito found".

Representative overlays:

```text
artifacts/stage1_candidate_eval_20260702/heuristics_reality/samples
```

## Input and Bbox Scale Diagnostics

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/diagnose_detector_input_alignment.py \
  --ann-file data/processed/stage1_candidate_eval_coco/annotations/instances_reality2017.json \
  --image-dir data/processed/stage1_candidate_eval_coco/reality2017 \
  --phone-image-dir data/processed/stage1_candidate_eval_coco/phone_frames/reality2017 \
  --output-dir artifacts/stage1_candidate_eval_20260702/input_bbox_stats_reality_full \
  --num-images 0 \
  --sample-images 60
```

Output:

```text
artifacts/stage1_candidate_eval_20260702/input_bbox_stats_reality_full
```

Full `reality2017` bbox stats:

| Stat | Value |
| --- | ---: |
| Boxes | 201 |
| Width p50 | 33.13 px |
| Height p50 | 17.98 px |
| Min-side p50 | 17.55 px |
| Min-side p10 | 12.57 px |
| Min-side < 12 px | 14 boxes |
| Model/source aspect multiplier | 1.78x |

Interpretation:

- The target is usually visible in the 416 input, but it is still a small target: median height is only about 18 px.
- The current camera preprocessing stretches 1080x1920 phone frames into 416x416. That changes mosquito shape by about `1.78x` in aspect ratio.
- More detector training without fixing or explicitly modeling this preprocessing mismatch is unlikely to produce stable Stage 1 guidance.

## YOLOX Alignment Diagnostic

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/diagnose_detector_input_alignment.py \
  --ann-file data/processed/stage1_candidate_eval_coco/annotations/instances_reality2017.json \
  --image-dir data/processed/stage1_candidate_eval_coco/reality2017 \
  --phone-image-dir data/processed/stage1_candidate_eval_coco/phone_frames/reality2017 \
  --output-dir artifacts/stage1_candidate_eval_20260702/yolox_alignment_reality \
  --num-images 360 \
  --sample-images 60 \
  --yolox-checkpoint artifacts/yolox_best_current/best.pt \
  --yolox-exp-module training.yolox_tiny_candidate_v2 \
  --yolox-device cpu \
  --yolox-conf 0.01 \
  --yolox-nms 0.45 \
  --max-predictions 8
```

Output:

```text
artifacts/stage1_candidate_eval_20260702/yolox_alignment_reality
```

Result on 360 images:

| Metric | Value |
| --- | ---: |
| Positive images | 54 |
| Images with YOLOX detections | 99 |
| Mean YOLOX detections/image | 1.38 |
| Images with prediction IoU >= 0.3 | 0 |
| Mean best IoU on positives | 0.0086 |
| Max best IoU | 0.132 |

Interpretation:

- YOLOX does emit boxes at very low threshold.
- The boxes usually land on nearby dark artifacts, not the mosquito.
- The failure is alignment/domain behavior, not merely "threshold too high".

Representative overlays:

```text
artifacts/stage1_candidate_eval_20260702/yolox_alignment_reality/samples
```

## D-FINE Alignment Diagnostic

Command:

```bash
/Users/nsaviour/AgentTeam/workplace/codeProject/ml-frameworks/.venvs/mosquito-train/bin/python \
  training/evaluate_dfine_coreml_detector.py \
  --model Mosquito-finder/DfineMosquitoDetector.mlpackage \
  --ann-file data/processed/stage1_candidate_eval_coco/annotations/instances_reality2017.json \
  --image-dir data/processed/stage1_candidate_eval_coco/reality2017 \
  --output artifacts/stage1_candidate_eval_20260702/dfine_reality_eval_with_visuals.json \
  --image-size 416 \
  --base-conf 0.01 \
  --nms 0.42 \
  --thresholds 0.01,0.03,0.05,0.08,0.10,0.15,0.20,0.30,0.40,0.50 \
  --num-images 360 \
  --visualize-dir artifacts/stage1_candidate_eval_20260702/dfine_alignment_reality/samples \
  --visualize-limit 60
```

Result on 360 images:

| Metric | Value |
| --- | ---: |
| Ground-truth boxes | 57 |
| Raw detections at base confidence | 12668 |
| Best threshold | 0.10 |
| Best precision | 0.033% |
| Best recall | 1.75% |
| Best F1 | 0.064% |
| True positives at best F1 | 1 |
| False positives at best F1 | 3052 |

Interpretation:

- D-FINE is not suitable as direct Stage 1 guidance on this semi-real wide-search set.
- At low threshold it produces many large or shifted boxes; raising threshold removes nearly all true positives.
- Current App behavior should rely on candidate search and stability, not full-frame D-FINE confidence, when the user is scanning a room.

Representative overlays:

```text
artifacts/stage1_candidate_eval_20260702/dfine_alignment_reality/samples
```

## Engineering Conclusions

1. Stage 1 should remain a candidate search layer.
   It should combine low-cost image processing, candidate stability, and optional candidate classification. It should not present detector output as a confirmed mosquito.

2. Traditional candidates are useful but insufficient.
   The current heuristic reaches about 54% positive hit rate overall, but fails on the exact hard cases that matter most: dark bags, cabinet undersides, and fabric.

3. YOLOX and D-FINE are not ready for full-frame Stage 1 on phone search scenes.
   YOLOX predicts the wrong dark artifacts; D-FINE emits too many false boxes. More training without addressing data alignment and target semantics is not the right next move.

4. The 416 stretch should be revisited.
   Phone frames are tall, but the current model path stretches them to square. This changes target shape by about `1.78x`. Future detector training and App preprocessing must either:
   - keep the stretch and train all detector data with the same distortion, or
   - move to aspect-preserving letterbox/crop and update coordinate deprojection.

## Next Implementation Steps

1. Add a Stage 1 candidate gate model behind the heuristic candidates.
   Use the existing experimental `CandidateSearchClassifier.mlmodel` only after validating it on this `stage1_candidate_eval_coco` crop set.

2. Build a candidate-crop eval manifest from `stage1_candidate_eval_coco`.
   Label crops as candidate-positive if they hit the mosquito by center-expanded matching, and negative otherwise.

3. Tune Stage 1 settings by scenario.
   Increase recall on `black_bag`, `cabinet_under`, and `fabric`, even if that means more false candidates; Stage 2 can reject them.

4. Change detector retraining strategy.
   Before another YOLOX/D-FINE run, visualize train-time input samples and enforce the same camera preprocessing used by the App.

5. Keep UI language conservative.
   The user should see "possible area" / "move closer" / "confirming", not "mosquito found" during Stage 1.
