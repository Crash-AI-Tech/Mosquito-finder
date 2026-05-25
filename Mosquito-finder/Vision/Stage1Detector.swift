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
    
    // MARK: - Private Properties
    
    private let ciContext = CIContext(options: [.useSoftwareRenderer: false, .priorityRequestLow: true])
    private var lastFrameTime: Date?
    private var isBusy = false
    
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
                
                let isSmoothBackground = bgVariance < 0.008  // 中间值：排除花纹/阴影背景
                let isLocallyDark = (bgMean - brightnessValues[0]) > 0.12  // 恢复适当对比度要求
                
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
}
