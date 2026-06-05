# 模型重训练与 D-FINE 接入计划

## 目标

把 D-FINE 这轮有效的训练方法沉淀成三条可重复链路：

1. 用同一批强化检测数据重训 YOLOX，更新 `YoloxMosquitoDetector.mlmodel`。
2. 从检测数据裁剪 Stage-2 ROI，重训 `MosquitoClassifier.mlmodel`。
3. 将训练好的 D-FINE 权重规范转换成 App 可加载的 `DfineMosquitoDetector.mlpackage`。

## 当前判断

- D-FINE 变好主要来自数据和验证方式：更大的 `generated_dfine` 数据集、更多 hard negative、低阳性率 `reality2017` 验证集，以及更长训练。
- YOLOX 旧模型只吃了早期 `generated` 数据，训练轮数也短，应该复用 `generated_dfine` 重训。
- `MosquitoClassifier` 是 64x64 二分类器，不能直接吃 COCO 检测标注；需要先从检测框和负样本区域裁剪 ROI。
- D-FINE 接入 App 的标准链路是 `pth -> ONNX 留档 -> CoreML mlpackage -> Xcode target -> Vision 输出解析`。当前已验证 `best_stg2.pth` 可以稳定导出固定 416 输入的 ONNX，并已通过 CoreMLTools 的 PyTorch 路径导出 `DfineMosquitoDetector.mlpackage`。

## 分阶段实施

### Phase 1：训练链路固化

已新增/调整：

- `training/yolox_mosquito_nano_reality.py`
  - 复用 `data/detector/generated_dfine`
  - 拉长训练到 18 epoch
  - 用 `reality2017` 作为更接近真实误报压力的验证集

- `training/build_classifier_crops_from_detector.py`
  - 从 COCO 检测数据裁剪正样本 ROI
  - 从无框图和非目标区域生成 hard negative ROI
  - 输出 `artifacts/classifier_detector_crops/manifest.csv`

- `training/export_coreml.py`
  - 支持 `--manifest`、`--output`
  - 默认提高负样本权重，优先压误报

- `training/export_dfine_coreml.py`
  - 读取 D-FINE `best_stg2.pth`
  - 导出固定 416 输入的单输入 ONNX 留档
  - 将 D-FINE Integral 中 CoreMLTools 不接受的 `F.linear` 改写为等价的 `softmax * weight -> sum`
  - 转换为 `DfineMosquitoDetector.mlpackage`，输出 raw `scores` 和 normalized `boxes`

- App 端补齐 D-FINE feature 输出解析：
  - D-FINE 输出 `scores` 时，App 可从 `VNCoreMLFeatureValueObservation` 中取最大置信度。
  - `D-FINE Detector` 会在模型文件实际内置后自动成为可选运行模式。

### Phase 2：实际重训练

推荐命令：

```bash
cd /Users/nsaviour/Desktop/workplace/codeProject/Mosquito-finder

# 1. 重训 YOLOX
PYTHONPATH=external/YOLOX:. .venv/bin/python external/YOLOX/tools/train.py \
  -f training/yolox_mosquito_nano_reality.py \
  -d 1 -b 8 \
  -c artifacts/pretrained/yolox_nano.pth

# 2. 生成分类器 ROI 数据
.venv/bin/python training/build_classifier_crops_from_detector.py --clean

# 3. 重训并导出 MosquitoClassifier.mlmodel
.venv/bin/python training/export_coreml.py \
  --manifest artifacts/classifier_detector_crops/manifest.csv \
  --output Mosquito-finder/MosquitoClassifier.mlmodel \
  --negative-weight 1.8 \
  --positive-weight 1.0

# 4. 导出 D-FINE CoreML
.venv/bin/python training/export_dfine_coreml.py \
  --checkpoint artifacts/dfine_mosquito_n_long/best_stg2.pth \
  --mlmodel-output Mosquito-finder/DfineMosquitoDetector.mlpackage
```

## D-FINE CoreML 转换状态

已验证：

- `training/export_dfine_coreml.py` 可以从 `best_stg2.pth` 导出 `DfineMosquitoDetectorScores.onnx`。
- 隔离环境 `.venv-coreml-dfine` 中，`onnxsim` 可以进一步生成 `DfineMosquitoDetectorScores.sim.onnx`。
- CoreMLTools 9 的 PyTorch trace 路径会卡在 D-FINE decoder 的 `linear` shape。
- CoreMLTools 4.x 的 ONNX converter 能读简化 ONNX，但不支持 D-FINE 图中的 `GatherElements` 和 `GridSample`。
- PyPI 上 Python 3.9 可装的 `onnx-coreml` 与 CoreMLTools 4.x API 不匹配，缺 `coremltools.converters.nnssa`。
- 将 Integral 的 `F.linear` 改写为等价乘加后，CoreMLTools 9 可以成功导出完整 D-FINE raw 输出模型。
- `Mosquito-finder/DfineMosquitoDetector.mlpackage` 已通过 `coremlc` 编译。
- Xcode 已能在 build 阶段把 `.mlpackage` 编译进 App，产物为 `DfineMosquitoDetector.mlmodelc`。

因此，D-FINE 端侧接入已经打通到 CoreML/Xcode build 层。下一步重点从“转换”转为“真机验收”：

1. 在 App 内切换到 `D-FINE Detector`，确认模型可加载。
2. 验证 `scores` 输出解析和阈值是否匹配真实效果。
3. 测量真机单次推理耗时和发热。
4. 与 YOLOX / CoreML Strict 做同场景误报、漏报对比。

## D-FINE CoreML 本地验收

已新增 `training/validate_coreml_detectors.py`，用于直接跑 CoreML Runtime，扫描 COCO split 的正负样本置信度分布。

当前 `DfineMosquitoDetector.mlpackage` 本地结果：

- `val2017`
  - 480 张，300 正样本，180 负样本
  - 平均推理约 4.87ms，p95 约 4.83ms
  - 阈值 0.50：precision 0.978，recall 0.910
  - 阈值 0.80：precision 0.995，recall 0.727

- `reality2017`
  - 720 张，192 正样本，528 负样本
  - 平均推理约 4.03ms，p95 约 4.73ms
  - 阈值 0.50：precision 0.951，recall 0.917
  - 阈值 0.80：precision 1.000，recall 0.714

因此 App 中 D-FINE 使用独立录屏验收预设，`stage2ConfidenceThreshold = 0.50`。这个阈值在真机拍屏、轻微虚焦和压缩场景下更容易触发；如果正式上架后误报压力更高，再把阈值提高到 `0.60-0.80`。

### Phase 3：验收与选择默认模型

验收顺序：

1. 编译验证：`xcodebuild ... CODE_SIGNING_ALLOWED=NO build`
2. CoreML 编译验证：确认 `coremlc` 能编译两个 `.mlmodel` 和一个 `.mlpackage`
3. App 内切换验证：
   - `D-FINE Detector`
   - `YOLOX Detector`
   - `CoreML Strict`
   - `CoreML Balanced`
4. 真实场景验证：
   - 无蚊墙面、木纹、布料、屏幕、阴影、污渍不能误报
   - 小黑点目标能稳定触发提示
   - 重点看 precision，宁可漏一点，也不能乱报

## 默认策略

- 如果 D-FINE CoreML 在 iPhone 上速度可接受且误报最低，设为默认。
- 如果 D-FINE 转换或端侧速度不稳定，保留 D-FINE 为可选，继续用 YOLOX Detector 作为默认。
- `MosquitoClassifier` 保留为轻量 Stage-2 fallback，用严格阈值压误报。
