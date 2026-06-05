//
//  Stage1Detector.swift
//  Mosquito-finder
//
//  Stage 1 Radar 检测器 - 检测白墙上的黑点/暗斑
//

import Foundation
import Combine
import CoreImage
import CoreVideo
import CoreML
import Vision
import UIKit

/// Stage 1 雷达检测器
/// 目标：高召回率，高效低能耗
class Stage1Detector: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var isProcessing = false
    @Published var lastProcessingTime: TimeInterval = 0
    @Published var detectionCount: Int = 0
    
    // MARK: - Configuration
    
    /// 暗点亮度阈值 (0-1)，低于此值视为暗点
    var darknessThreshold: CGFloat = 0.25
    
    /// 最小检测数量
    var maxDetections: Int = 5
    
    /// 网格扫描大小 (缩小提升精度)
    var gridSize: Int = 32
    
    /// 帧率限制 (提升至 10 FPS)
    var frameInterval: TimeInterval = 0.1

    /// 背景平整度阈值
    var backgroundVarianceThreshold: Float = 0.015

    /// 中心暗点与周围背景的最小亮度差
    var localContrastThreshold: Float = 0.08

    /// 当前运行模型模式
    var modelMode: RuntimeModelMode = .coreMLStrict

    /// 检测模型候选阈值。Stage 1 用较低阈值提高召回，Stage 2 再做确认。
    var detectorCandidateThreshold: Float = 0.35
    
    // MARK: - Private Properties
    
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false, .priorityRequestLow: true])
    private var lastFrameTime: Date?
    private var isBusy = false
    private var loadedDetectorMode: RuntimeModelMode?
    private var detectorModel: MLModel?
    
    // MARK: - Public Methods
    
    /// 检测帧中的暗点区域
    func detectDarkSpots(pixelBuffer: CVPixelBuffer) -> [SuspectRegion] {
        // 1. 严格频率限制
        let now = Date()
        if let last = lastFrameTime, now.timeIntervalSince(last) < frameInterval {
            return []
        }
        
        // 防止重入
        if isBusy { return [] }
        isBusy = true
        
        lastFrameTime = now
        let startTime = now
        
        // 在后台同步记录处理状态 (通过 MainActor 回调)
        DispatchQueue.main.async { self.isProcessing = true }
        
        var cachedRegions: [SuspectRegion] = []
        
        defer {
            let duration = Date().timeIntervalSince(startTime)
            let count = cachedRegions.count
            DispatchQueue.main.async {
                self.isProcessing = false
                self.lastProcessingTime = duration
                self.detectionCount = count
            }
            isBusy = false
        }
        
        if modelMode.isDetectorMode,
           let detectorRegions = detectWithFullFrameDetector(pixelBuffer: pixelBuffer) {
            cachedRegions = detectorRegions
            return cachedRegions
        }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            return []
        }
        
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        let buffer = baseAddress.assumingMemoryBound(to: UInt8.self)
        
        var processedCenters: [(x: Int, y: Int)] = []
        
        // 边缘排除 margin：3倍 gridSize 避免镜头暗角假阳性
        let edgeMargin = gridSize * 3
        
        // 2. 超高精度采样与背景分析优化
        for gridY in stride(from: edgeMargin, to: height - edgeMargin, by: gridSize) {
            for gridX in stride(from: edgeMargin, to: width - edgeMargin, by: gridSize) {
                
                // 采集样本点（采样间距缩小，更适配微小目标）
                let sampleOffsets = [
                    (0, 0), 
                    (-10, -10), (0, -10), (10, -10),
                    (-10, 0),             (10, 0),
                    (-10, 10),  (0, 10),  (10, 10)
                ]
                
                var brightnessValues: [Float] = []
                for offset in sampleOffsets {
                    let sx = gridX + offset.0
                    let sy = gridY + offset.1
                    let bufferOffset = sy * bytesPerRow + sx * 4
                    
                    let b = Float(buffer[bufferOffset])
                    let g = Float(buffer[bufferOffset + 1])
                    let r = Float(buffer[bufferOffset + 2])
                    brightnessValues.append((r + g + b) / (3.0 * 255.0))
                }
                
                // 计算背景均值和方差（排除中心点 [0]，只看周围背景的平整度）
                let backgroundSamples = Array(brightnessValues.dropFirst())
                let bgMean = backgroundSamples.reduce(0, +) / Float(backgroundSamples.count)
                let bgVariance = backgroundSamples.reduce(0) { $0 + pow($1 - bgMean, 2) } / Float(backgroundSamples.count)
                
                // 排除策略优化：
                // 1. 背景必须平整 (更严格的方差控制)
                // 2. 局部对比度 (提高暗点判定置信度)
                
                let isSmoothBackground = bgVariance < backgroundVarianceThreshold
                let isLocallyDark = (bgMean - brightnessValues[0]) > localContrastThreshold
                
                if isSmoothBackground && isLocallyDark {
                    let centerX = CGFloat(gridX)
                    let centerY = CGFloat(gridY)
                    
                    // 距离过滤
                    let tooClose = processedCenters.contains { existing in
                        abs(gridX - existing.x) < gridSize && abs(gridY - existing.y) < gridSize
                    }
                    
                    if !tooClose && cachedRegions.count < maxDetections {
                        let size: CGFloat = CGFloat(gridSize) * 0.7
                        cachedRegions.append(SuspectRegion(
                            boundingBox: CGRect(x: centerX - size/2, y: centerY - size/2, width: size, height: size),
                            confidence: Float(bgMean - brightnessValues[0]) * 3.0 // 提升置信度权重
                        ))
                        processedCenters.append((gridX, gridY))
                    }
                }
            }
        }
        
        return cachedRegions
    }

    // MARK: - Full-frame detector path

    private func detectWithFullFrameDetector(pixelBuffer: CVPixelBuffer) -> [SuspectRegion]? {
        guard let model = loadDetectorModel(for: modelMode),
              let resizedBuffer = resize(pixelBuffer: pixelBuffer, width: 416, height: 416) else {
            return nil
        }

        do {
            let input = try MLDictionaryFeatureProvider(dictionary: [
                "images": MLFeatureValue(pixelBuffer: resizedBuffer)
            ])
            let output = try model.prediction(from: input)
            let imageSize = CGSize(
                width: CVPixelBufferGetWidth(pixelBuffer),
                height: CVPixelBufferGetHeight(pixelBuffer)
            )

            switch modelMode {
            case .detectorDfine:
                return parseDfineDetections(
                    scores: output.featureValue(for: "scores")?.multiArrayValue,
                    boxes: output.featureValue(for: "boxes")?.multiArrayValue,
                    imageSize: imageSize
                )
            case .detectorYolox:
                return parseYoloxDetections(
                    output: output.featureValue(for: "output")?.multiArrayValue,
                    imageSize: imageSize
                )
            case .coreMLStrict, .coreMLBalanced:
                return nil
            }
        } catch {
            print("Detector Stage 1 检测失败: \(error)")
            return nil
        }
    }

    private func loadDetectorModel(for mode: RuntimeModelMode) -> MLModel? {
        if loadedDetectorMode == mode, let detectorModel {
            return detectorModel
        }

        guard let modelName = mode.bundledModelName,
              let modelURL = Bundle.main.url(forResource: modelName, withExtension: "mlmodelc") else {
            detectorModel = nil
            loadedDetectorMode = nil
            return nil
        }

        do {
            let config = MLModelConfiguration()
            config.computeUnits = .all
            let model = try MLModel(contentsOf: modelURL, configuration: config)
            detectorModel = model
            loadedDetectorMode = mode
            return model
        } catch {
            print("Detector Stage 1 模型加载失败: \(error)")
            detectorModel = nil
            loadedDetectorMode = nil
            return nil
        }
    }

    private func resize(pixelBuffer: CVPixelBuffer, width: Int, height: Int) -> CVPixelBuffer? {
        var resizedBuffer: CVPixelBuffer?
        let attrs = [
            kCVPixelBufferCGImageCompatibilityKey: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey: true
        ] as CFDictionary

        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attrs,
            &resizedBuffer
        )

        guard status == kCVReturnSuccess, let resizedBuffer else { return nil }

        let image = CIImage(cvPixelBuffer: pixelBuffer)
        let scaleX = CGFloat(width) / image.extent.width
        let scaleY = CGFloat(height) / image.extent.height
        let resizedImage = image.transformed(by: CGAffineTransform(scaleX: scaleX, y: scaleY))
        ciContext.render(resizedImage, to: resizedBuffer)
        return resizedBuffer
    }

    private func parseDfineDetections(
        scores: MLMultiArray?,
        boxes: MLMultiArray?,
        imageSize: CGSize
    ) -> [SuspectRegion] {
        guard let scores, let boxes else { return [] }

        let candidateCount = min(scores.count, boxes.shape.count >= 2 ? boxes.shape[boxes.shape.count - 2].intValue : scores.count)
        var detections: [SuspectRegion] = []

        for index in 0..<candidateCount {
            let scoreIndexes = [NSNumber(value: 0), NSNumber(value: index), NSNumber(value: 0)]
            let confidence = Float(truncating: scores[scoreIndexes])
            guard confidence >= detectorCandidateThreshold else { continue }

            let cx = CGFloat(truncating: boxes[[NSNumber(value: 0), NSNumber(value: index), NSNumber(value: 0)]])
            let cy = CGFloat(truncating: boxes[[NSNumber(value: 0), NSNumber(value: index), NSNumber(value: 1)]])
            let width = CGFloat(truncating: boxes[[NSNumber(value: 0), NSNumber(value: index), NSNumber(value: 2)]])
            let height = CGFloat(truncating: boxes[[NSNumber(value: 0), NSNumber(value: index), NSNumber(value: 3)]])

            let rect = clamp(
                CGRect(
                    x: (cx - width / 2) * imageSize.width,
                    y: (cy - height / 2) * imageSize.height,
                    width: width * imageSize.width,
                    height: height * imageSize.height
                ),
                to: imageSize
            )

            guard rect.width >= 4, rect.height >= 4 else { continue }
            detections.append(SuspectRegion(boundingBox: rect, confidence: confidence))
        }

        return detections
            .sorted { $0.confidence > $1.confidence }
            .prefix(maxDetections)
            .map { $0 }
    }

    private func parseYoloxDetections(
        output: MLMultiArray?,
        imageSize: CGSize
    ) -> [SuspectRegion] {
        guard let output, output.shape.count >= 3 else { return [] }

        let candidateCount = output.shape[output.shape.count - 2].intValue
        let valueCount = output.shape[output.shape.count - 1].intValue
        guard valueCount >= 5 else { return [] }

        var detections: [SuspectRegion] = []
        for index in 0..<candidateCount {
            let objectness = detectorValue(output, candidate: index, value: 4)
            let classConfidence = valueCount > 5 ? detectorValue(output, candidate: index, value: 5) : 1
            let confidence = objectness * classConfidence
            guard confidence >= detectorCandidateThreshold else { continue }

            let x1 = CGFloat(detectorValue(output, candidate: index, value: 0)) / 416.0 * imageSize.width
            let y1 = CGFloat(detectorValue(output, candidate: index, value: 1)) / 416.0 * imageSize.height
            let x2 = CGFloat(detectorValue(output, candidate: index, value: 2)) / 416.0 * imageSize.width
            let y2 = CGFloat(detectorValue(output, candidate: index, value: 3)) / 416.0 * imageSize.height
            let rect = clamp(
                CGRect(
                    x: min(x1, x2),
                    y: min(y1, y2),
                    width: abs(x2 - x1),
                    height: abs(y2 - y1)
                ),
                to: imageSize
            )

            guard rect.width >= 4, rect.height >= 4 else { continue }
            detections.append(SuspectRegion(boundingBox: rect, confidence: confidence))
        }

        return nonMaximumSuppressed(detections)
            .prefix(maxDetections)
            .map { $0 }
    }

    private func nonMaximumSuppressed(_ detections: [SuspectRegion], iouThreshold: CGFloat = 0.45) -> [SuspectRegion] {
        var selected: [SuspectRegion] = []
        let sortedDetections = detections.sorted { $0.confidence > $1.confidence }

        for detection in sortedDetections {
            let overlapsSelected = selected.contains {
                intersectionOverUnion(detection.boundingBox, $0.boundingBox) >= iouThreshold
            }
            if !overlapsSelected {
                selected.append(detection)
            }
        }

        return selected
    }

    private func intersectionOverUnion(_ lhs: CGRect, _ rhs: CGRect) -> CGFloat {
        let intersection = lhs.intersection(rhs)
        guard !intersection.isNull else { return 0 }
        let intersectionArea = intersection.width * intersection.height
        let unionArea = lhs.width * lhs.height + rhs.width * rhs.height - intersectionArea
        return unionArea > 0 ? intersectionArea / unionArea : 0
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

    private func clamp(_ rect: CGRect, to imageSize: CGSize) -> CGRect {
        let x = max(0, min(rect.origin.x, imageSize.width))
        let y = max(0, min(rect.origin.y, imageSize.height))
        let maxWidth = max(0, imageSize.width - x)
        let maxHeight = max(0, imageSize.height - y)

        return CGRect(
            x: x,
            y: y,
            width: max(0, min(rect.width, maxWidth)),
            height: max(0, min(rect.height, maxHeight))
        )
    }
}
