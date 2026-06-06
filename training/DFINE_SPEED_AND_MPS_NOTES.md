# D-FINE Speed and MPS Notes

Generated: 2026-06-06

## Current CPU Baseline

D-FINE combined COCO CPU baseline completed 4 epochs with:

- Best checkpoint: `artifacts/dfine_combined_coco_cpu/best_stg2.pth`
- Runtime: `2:15:38`
- Best AP@[0.50:0.95]: `0.187`
- Best AP@0.50: `0.441`
- Best built-in precision / recall / F1: `71.41% / 21.87% / 33.48%`

The epoch trend is still improving, so the model has not converged.

## CPU Worker and Thread Benchmark

Short smoke benchmarks on the combined COCO config:

| Device | Torch threads | Data workers | Steps | Seconds / step |
| --- | ---: | ---: | ---: | ---: |
| CPU | 8 | 0 | 20 | 0.907 |
| CPU | 8 | 2 | 20 | 0.903 |
| CPU | 12 | 0 | 20 | 1.222 |

Adding dataloader workers does not materially improve throughput. The training loop is compute-bound on the model, not input-bound on image loading. Too many Torch threads can make CPU training slower.

Recommended CPU setting for follow-up runs:

```bash
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 torchrun_or_python_command ...
```

Use `num_workers=0` or `2`; do not expect a large speed-up from dataloader workers.

## MPS Compatibility

The original D-FINE decoder failed on MPS at the `Integral` projection with an MPSGraph matmul shape error:

```text
'mps.matmul' op contracting dimensions differ 8000 & 33
```

`training/train_dfine_cpu_smoke.py` now includes an optional MPS-friendly `Integral` implementation:

```bash
PYTORCH_ENABLE_MPS_FALLBACK=1 python training/train_dfine_cpu_smoke.py \
  --config training/dfine_combined_coco_cpu.yml \
  --device mps \
  --mps-friendly-integral
```

This fixes the decoder matmul crash for the smoke loop, but full training is still not faster on MPS because PyTorch falls back to CPU for:

```text
aten::grid_sampler_2d_backward
```

Measured MPS smoke speed with the workaround:

| Device | Steps | Seconds / step | Notes |
| --- | ---: | ---: | --- |
| MPS | 3 | 5.889 | Runs, but backward falls back to CPU |

## Decision

Do not switch full D-FINE training to MPS yet. The first decoder compatibility problem is fixed, but current PyTorch MPS support still makes the backward pass too slow for this architecture.

For now:

1. Keep CPU baseline as the reliable path.
2. Use 8 Torch threads for CPU runs.
3. Continue D-FINE only if the longer-run metric gain justifies CPU time.
4. Revisit MPS when the deformable sampling backward path is supported or a model/config path avoids it.
