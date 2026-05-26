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
    
    /// 置信度阈值
    var confidenceThreshold: Float = 0.90  // 提高阈值降低假阳性
    
    /// ROI 区域大小（相对于屏幕中心）
    var roiSize: CGSize = CGSize(width: 224, height: 224)
    
    // MARK: - Private Properties
    
    private var classificationRequest: VNCoreMLRequest?
    private var isModelLoaded = false
    
    // MARK: - Init
    
    init() {
        loadModel()
    }
    
    // MARK: - Public Methods
    
    /// 分类指定区域
    func classify(region: CGRect, in pixelBuffer: CVPixelBuffer) -> ClassificationResult {
        let startTime = Date()
        isProcessing = true
        defer {
            isProcessing = false
            lastProcessingTime = Date().timeIntervalSince(startTime)
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
            
            if let results = request.results as? [VNClassificationObservation],
               let topResult = results.first {
                
                let isMosquito = topResult.identifier.lowercased().contains("mosquito")
                let result = ClassificationResult(
                    isMosquito: isMosquito && topResult.confidence >= confidenceThreshold,
                    confidence: topResult.confidence,
                    processingTime: Date().timeIntervalSince(startTime)
                )
                
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
            
            let model = try MosquitoClassifier(configuration: config)
            let visionModel = try VNCoreMLModel(for: model.model)
            
            classificationRequest = VNCoreMLRequest(model: visionModel) { [weak self] request, error in
                if let error = error {
                    print("分类请求错误: \(error)")
                }
            }
            
            classificationRequest?.imageCropAndScaleOption = .centerCrop
            isModelLoaded = true
            
        } catch {
            print("模型加载失败: \(error)")
            isModelLoaded = false
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
    
    /// 提取区域特征
    private func extractRegionFeatures(region: CGRect, from pixelBuffer: CVPixelBuffer) -> RegionFeatures {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            return RegionFeatures(averageBrightness: 0.5, contrast: 0.5)
        }
        
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        
        // 确保区域在图像范围内
        let clampedRegion = CGRect(
            x: max(0, min(region.origin.x, CGFloat(width - 1))),
            y: max(0, min(region.origin.y, CGFloat(height - 1))),
            width: min(region.width, CGFloat(width) - region.origin.x),
            height: min(region.height, CGFloat(height) - region.origin.y)
        )
        
        var totalBrightness: Float = 0
        var minBrightness: Float = 1
        var maxBrightness: Float = 0
        var pixelCount: Float = 0
        
        let buffer = baseAddress.assumingMemoryBound(to: UInt8.self)
        
        for y in Int(clampedRegion.origin.y)..<Int(clampedRegion.origin.y + clampedRegion.height) {
            for x in Int(clampedRegion.origin.x)..<Int(clampedRegion.origin.x + clampedRegion.width) {
                let offset = y * bytesPerRow + x * 4
                
                let b = Float(buffer[offset]) / 255.0
                let g = Float(buffer[offset + 1]) / 255.0
                let r = Float(buffer[offset + 2]) / 255.0
                
                let brightness = (r + g + b) / 3.0
                
                totalBrightness += brightness
                minBrightness = min(minBrightness, brightness)
                maxBrightness = max(maxBrightness, brightness)
                pixelCount += 1
            }
        }
        
        let averageBrightness = pixelCount > 0 ? totalBrightness / pixelCount : 0.5
        let contrast = maxBrightness - minBrightness
        
        return RegionFeatures(averageBrightness: averageBrightness, contrast: contrast)
    }
}

// MARK: - Supporting Types

struct RegionFeatures {
    let averageBrightness: Float
    let contrast: Float
}
