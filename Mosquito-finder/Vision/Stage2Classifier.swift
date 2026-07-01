//
//  Stage2Classifier.swift
//  Mosquito-finder
//
//  Stage 2 Sniper 分类器 - 高精度蚊子识别
//

import Foundation
import Combine
import Vision
import CoreVideo
import CoreML
import UIKit

/// Stage 2 狙击分类器
/// 目标：高精度识别蚊子
class Stage2Classifier: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var isProcessing = false
    @Published var lastResult: ClassificationResult?
    @Published var lastProcessingTime: TimeInterval = 0
    
    // MARK: - Configuration
    
    /// 置信度阈值。当前阶段优先压误报，和离线高 precision 评估阈值保持一致。
    var confidenceThreshold: Float = 0.90

    /// 当前运行模型模式
    var modelMode: RuntimeModelMode = .classic
    
    /// ROI 区域大小（相对于屏幕中心）
    var roiSize: CGSize = CGSize(width: 224, height: 224)
    
    // MARK: - Private Properties
    
    private var classificationRequest: VNCoreMLRequest?
    private var isModelLoaded = false
    private var loadedModelMode: RuntimeModelMode?
    
    // MARK: - Init
    
    init() {}
    
    // MARK: - Public Methods
    
    /// 分类指定区域
    func classify(region: CGRect, in pixelBuffer: CVPixelBuffer) -> ClassificationResult {
        let startTime = Date()
        isProcessing = true
        defer {
            isProcessing = false
            lastProcessingTime = Date().timeIntervalSince(startTime)
        }

        if !isModelLoaded {
            loadModel()
        }
        
        // 如果没有模型，使用模拟检测
        guard isModelLoaded, let request = classificationRequest else {
            return simulateClassification(region: region, in: pixelBuffer)
        }
        
        // 裁剪 ROI 区域
        let imageWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let imageHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
        
        // Vision 坐标系原点在左下角，需要翻转 Y 轴
        let nw = region.width / imageWidth
        let nh = region.height / imageHeight
        let nx = region.origin.x / imageWidth
        let ny = 1.0 - (region.origin.y / imageHeight) - nh  // Y 轴翻转
        let normalizedRegion = CGRect(
            x: max(0, min(1 - nw, nx)),
            y: max(0, min(1 - nh, ny)),
            width: max(0.01, nw),
            height: max(0.01, nh)
        )
        
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        request.regionOfInterest = normalizedRegion
        
        do {
            try handler.perform([request])
            
            if let result = parseClassificationResult(from: request, startTime: startTime) {
                lastResult = result
                return result
            }
        } catch {
            print("分类失败: \(error)")
        }
        
        return ClassificationResult(isMosquito: false, confidence: 0, processingTime: Date().timeIntervalSince(startTime))
    }
    
    /// 加载 CoreML 模型
    func loadModel() {
        do {
            let config = MLModelConfiguration()
            config.computeUnits = .all

            // Stage 2 is the precision gate for every profile. Detector profiles
            // use D-FINE/YOLOX only for full-frame candidate search, then confirm
            // an enlarged ROI with the dedicated mosquito classifier.
            let model = try MosquitoClassifier(configuration: config)
            let visionModel = try VNCoreMLModel(for: model.model)
            
            classificationRequest = VNCoreMLRequest(model: visionModel) { _, error in
                if let error = error {
                    print("分类请求错误: \(error)")
                }
            }
            
            classificationRequest?.imageCropAndScaleOption = .centerCrop
            isModelLoaded = true
            loadedModelMode = modelMode
            
        } catch {
            print("模型加载失败: \(error)")
            isModelLoaded = false
            loadedModelMode = nil
        }
    }

    func apply(settings: RuntimeDetectionSettings) {
        confidenceThreshold = settings.stage2ConfidenceThreshold
        if modelMode != settings.modelMode {
            modelMode = settings.modelMode
            isModelLoaded = false
            classificationRequest = nil
            loadedModelMode = nil
        }
    }
    
    // MARK: - Private Methods
    
    /// 设置后备分类器（使用 Vision 内置能力）
    private func setupFallbackClassifier() {
        // 使用 Vision 的物体识别作为后备
        // 实际项目中应使用专门训练的蚊子模型
        isModelLoaded = false
    }
    
    /// 模拟分类（模型未加载时后备）
    /// 直接返回 false 避免误报——无模型时不应判断为蚊子
    private func simulateClassification(region: CGRect, in pixelBuffer: CVPixelBuffer) -> ClassificationResult {
        return ClassificationResult(isMosquito: false, confidence: 0, processingTime: 0)
    }

    private func parseClassificationResult(
        from request: VNCoreMLRequest,
        startTime: Date
    ) -> ClassificationResult? {
        if let results = request.results as? [VNClassificationObservation],
           let topResult = results.first {
            let isMosquito = normalizedLabel(topResult.identifier) == "mosquito"
            return ClassificationResult(
                isMosquito: isMosquito && topResult.confidence >= confidenceThreshold,
                confidence: topResult.confidence,
                processingTime: Date().timeIntervalSince(startTime)
            )
        }

        if let observations = request.results as? [VNRecognizedObjectObservation],
           let best = observations
            .flatMap({ $0.labels })
            .max(by: { $0.confidence < $1.confidence }) {
            let isMosquito = normalizedLabel(best.identifier) == "mosquito"
            return ClassificationResult(
                isMosquito: isMosquito && best.confidence >= confidenceThreshold,
                confidence: best.confidence,
                processingTime: Date().timeIntervalSince(startTime)
            )
        }

        if let featureObservations = request.results as? [VNCoreMLFeatureValueObservation],
           let confidence = bestFeatureDetectorConfidence(in: featureObservations) {
            return ClassificationResult(
                isMosquito: confidence >= confidenceThreshold,
                confidence: confidence,
                processingTime: Date().timeIntervalSince(startTime)
            )
        }

        return nil
    }

    private func bestFeatureDetectorConfidence(in observations: [VNCoreMLFeatureValueObservation]) -> Float? {
        if modelMode == .detectorDfine, let confidence = bestDfineConfidence(in: observations) {
            return confidence
        }
        return bestYoloxConfidence(in: observations)
    }

    private func bestDfineConfidence(in observations: [VNCoreMLFeatureValueObservation]) -> Float? {
        let scoreObservation = observations.first {
            $0.featureName.lowercased().contains("score")
        }

        guard let scores = scoreObservation?.featureValue.multiArrayValue else {
            return nil
        }

        var bestScore: Float = 0
        for index in 0..<scores.count {
            bestScore = max(bestScore, Float(truncating: scores[index]))
        }

        return bestScore
    }

    private func bestYoloxConfidence(in observations: [VNCoreMLFeatureValueObservation]) -> Float? {
        for observation in observations {
            guard let scores = observation.featureValue.multiArrayValue,
                  scores.shape.count >= 3,
                  scores.shape.last?.intValue ?? 0 >= 5 else {
                continue
            }

            let candidateCount = scores.shape[scores.shape.count - 2].intValue
            let valueCount = scores.shape[scores.shape.count - 1].intValue
            var bestScore: Float = 0

            for index in 0..<candidateCount {
                let objectness = detectorValue(scores, candidate: index, value: 4)
                let classConfidence = valueCount > 5 ? detectorValue(scores, candidate: index, value: 5) : 1
                bestScore = max(bestScore, objectness * classConfidence)
            }

            return bestScore
        }

        return nil
    }

    private func detectorValue(_ array: MLMultiArray, candidate: Int, value: Int) -> Float {
        let indexes: [NSNumber]
        if array.shape.count == 3 {
            indexes = [0, NSNumber(value: candidate), NSNumber(value: value)]
        } else {
            indexes = [NSNumber(value: candidate), NSNumber(value: value)]
        }

        return Float(truncating: array[indexes])
    }

    private func normalizedLabel(_ identifier: String) -> String {
        identifier
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func bundledDetectorModelURL(for mode: RuntimeModelMode) -> URL? {
        switch mode {
        case .detectorDfine:
            return Bundle.main.url(forResource: "DfineMosquitoDetector", withExtension: "mlmodelc")
        case .detectorYolox:
            return Bundle.main.url(forResource: "YoloxMosquitoDetector", withExtension: "mlmodelc")
        case .classic:
            return nil
        }
    }
    
}
