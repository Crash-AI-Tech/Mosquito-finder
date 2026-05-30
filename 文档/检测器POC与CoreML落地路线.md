# 检测器 POC 与 CoreML 落地路线

本文档对应三阶段路线：

1. 阶段一：先压当前 CoreML 二分类链路误报。
2. 阶段二：用同一批真实数据对比 D-FINE 与 YOLOX 检测器。
3. 阶段三：将胜出检测器转为 CoreML，并接入 iOS 实时流程。

## 阶段一：已实施的热修策略

当前版本优先降低误报：

* `Stage2Classifier.confidenceThreshold = 0.90`
* 移除高对比暗点直接确认逻辑，Stage2 只能由模型高置信结果确认。
* `TriggerEvaluator.minZoomFactor = 2.0`
* `TriggerEvaluator.centerRegionRatio = 0.25`
* `TriggerEvaluator.minTargetSize = 20`
* `TrackedTarget.isStable` 从 2 帧提高到 5 帧。

用户在 Found 状态点击“已处理”时，冻结帧会写入 App 沙盒：

```text
Documents/MosquitoFinderReview/candidate_hard_negative/
```

这些样本只是“候选 hard negative”，进入训练前必须人工复核，避免把真实蚊子误标成负样本。

## 阶段二：检测器 POC 数据格式

原始数据放在：

```text
data/detector/
├── images/
│   ├── sample_0001.jpg
│   └── sample_0002.jpg
└── labels/
    └── sample_0001.json
```

`labels/*.json` 使用像素坐标：

```json
{
  "boxes": [
    {
      "label": "mosquito",
      "x": 120.0,
      "y": 300.0,
      "width": 18.0,
      "height": 16.0
    }
  ]
}
```

纯负图不需要 json 文件，脚本会生成空 YOLO label。

生成 YOLO 格式 POC 数据集：

```bash
.venv/bin/python training/prepare_detector_poc_dataset.py --clean
```

输出：

```text
artifacts/detector_poc/
├── dataset.yaml
├── summary.json
├── images/train/
├── images/val/
├── labels/train/
└── labels/val/
```

## 阶段二：模型对比规则

第一轮只跑两个候选：

1. `D-FINE-N`：验证精度上限和复杂背景误报。
2. `YOLOX-Nano`：验证移动端部署稳定性和速度。

统一评估指标：

* precision：优先指标，目标 `>= 0.98`
* recall：第二指标，可先接受偏低
* false positives per 100 negative images
* iPhone 单帧延迟
* 连续运行 5 分钟发热/掉帧
* CoreML 转换是否无自定义算子

最小 POC 数据要求：

* 300 张带框真实蚊子图
* 1000 张家庭纯负图
* 每类复杂背景至少 100 张：墙纹、木纹、布料、插座、灰尘、阴影、屏幕、家具边缘

## 阶段三：CoreML 接入策略

胜出模型统一走：

```text
PyTorch checkpoint
  -> ONNX
  -> coremltools convert
  -> .mlpackage/.mlmodel
  -> Xcode 集成
  -> Vision VNCoreMLRequest
```

App 侧已经预留模型切换入口：

* 当前已接入并可直接测试：`CoreML Strict`、`CoreML Balanced`
* D-FINE 模型文件名：`DfineMosquitoDetector.mlmodel`
* YOLOX 模型文件名：`YoloxMosquitoDetector.mlmodel`

将检测器模型加入 App 时：

1. 把训练导出的 `.mlmodel` 拖入 `Mosquito-finder/` 目录。
2. 在 Xcode 中勾选 `Mosquito-finder` target membership。
3. 确认模型输出可被 Vision 解析为 `VNRecognizedObjectObservation`，类别名使用 `mosquito`。
4. 真机进入 Settings -> Runtime Model，选择对应检测器模式。

如果设置里选择了检测器模式，但 bundle 中没有对应模型，App 不会误报，会打印模型缺失并返回未确认结果。

端侧运行策略：

* 不全屏每帧跑检测器。
* 默认仍由 Stage1 做低成本候选发现。
* 用户放大且目标进入中心区域后，再对中心 ROI 跑检测器。
* 检测器结果需要 3 次时序确认后才进入 Found。
* 所有用户 dismiss 的 Found 结果继续进入候选 hard negative 目录。

## 验收标准

阶段一验收：

* 随机拍摄非蚊子区域 50 次，误触发 Found 明显下降。
* 对真实蚊子或蚊子图片仍能在 2x 以上触发。

阶段二验收：

* D-FINE-N 与 YOLOX-Nano 在同一验证集输出可比较报告。
* 每个模型至少给出 precision、recall、误报样例、漏检样例。

阶段三验收：

* CoreML 模型在真机可实时运行。
* 连续 5 分钟运行无明显卡顿。
* 误报样本能持续回流到复核目录。
