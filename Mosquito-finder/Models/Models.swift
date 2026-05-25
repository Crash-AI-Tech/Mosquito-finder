//
//  Models.swift
//  Mosquito-finder
//
//  Core data models for the Two-Stage Detection system
//

import Foundation
import SwiftUI
import CoreGraphics

// MARK: - Stage 1 Output

/// 可疑区域 - Stage 1 Radar 检测输出
struct SuspectRegion: Identifiable, Equatable {
    let id = UUID()
    var boundingBox: CGRect
    var confidence: Float
    var timestamp: Date
    
    init(boundingBox: CGRect, confidence: Float = 0.5, timestamp: Date = Date()) {
        self.boundingBox = boundingBox
        self.confidence = confidence
        self.timestamp = timestamp
    }
    
    /// 区域中心点
    var center: CGPoint {
        CGPoint(x: boundingBox.midX, y: boundingBox.midY)
    }
    
    /// 区域尺寸
    var size: CGSize {
        boundingBox.size
    }
}

// MARK: - Target State

/// 目标状态枚举
enum TargetState: String, CaseIterable {
    case suspect    // 黄色光圈 - 可疑
    case engaging   // 正在确认中
    case confirmed  // 红色锁定 - 确认是蚊子
    case dismissed  // 灰色叉号 - 确认不是蚊子
    
    var displayColor: String {
        switch self {
        case .suspect: return "yellow"
        case .engaging: return "orange"
        case .confirmed: return "red"
        case .dismissed: return "gray"
        }
    }
}

// MARK: - Tracked Target

/// 被追踪的目标
struct TrackedTarget: Identifiable, Equatable {
    let id: UUID
    var boundingBox: CGRect
    var trackingConfidence: Float
    var state: TargetState
    var lastUpdated: Date
    var framesSinceLastUpdate: Int = 0
    var detectedFrameCount: Int = 0 // 持续检测到的帧数
    var framesMissed: Int = 0       // 连续丢失的帧数
    var visibility: Double = 1.0    // 渲染透明度 (1.0 -> 0.0)
    
    init(
        id: UUID = UUID(),
        boundingBox: CGRect,
        trackingConfidence: Float = 1.0,
        state: TargetState = .suspect,
        lastUpdated: Date = Date(),
        detectedFrameCount: Int = 1,
        visibility: Double = 1.0
    ) {
        self.id = id
        self.boundingBox = boundingBox
        self.trackingConfidence = trackingConfidence
        self.state = state
        self.lastUpdated = lastUpdated
        self.detectedFrameCount = detectedFrameCount
        self.visibility = visibility
    }
    
    /// 目标中心点
    var center: CGPoint {
        CGPoint(x: boundingBox.midX, y: boundingBox.midY)
    }
    
    /// 目标尺寸
    var size: CGSize {
        boundingBox.size
    }
    
    /// 目标是否稳定（至少持续出现 5 帧 ≈ 0.5s，减少噪点误报）
    var isStable: Bool {
        detectedFrameCount >= 5
    }
    
    /// 是否足够大以触发 Stage 2
    var isBigEnough: Bool {
        size.width >= 50 && size.height >= 50
    }
    
    /// 目标是否已过期（长时间未更新）
    var isStale: Bool {
        framesSinceLastUpdate > 30 // 约 1 秒 @ 30fps
    }
    
    static func == (lhs: TrackedTarget, rhs: TrackedTarget) -> Bool {
        lhs.id == rhs.id
    }
}

// MARK: - Classification Result

/// Stage 2 分类结果
struct ClassificationResult {
    let isMosquito: Bool
    let confidence: Float
    let processingTime: TimeInterval
    let timestamp: Date
    
    init(isMosquito: Bool, confidence: Float, processingTime: TimeInterval = 0) {
        self.isMosquito = isMosquito
        self.confidence = confidence
        self.processingTime = processingTime
        self.timestamp = Date()
    }
    
    /// 置信度百分比字符串
    var confidencePercentage: String {
        String(format: "%.0f%%", confidence * 100)
    }
}

// MARK: - Hunting Phase

/// 狩猎阶段
enum HuntingPhase: String, CaseIterable {
    case idle       // 空闲/启动中
    case scanning   // 广角搜索 (Stage 1)
    case engaging   // 锁定确认中
    case killing    // 已确认目标
    
    var displayName: String {
        switch self {
        case .idle:     return NSLocalizedString("Ready",     comment: "Hunting phase: idle")
        case .scanning: return NSLocalizedString("Scanning",  comment: "Hunting phase: scanning")
        case .engaging: return NSLocalizedString("Targeting", comment: "Hunting phase: engaging")
        case .killing:  return NSLocalizedString("Found!",    comment: "Hunting phase: mosquito confirmed")
        }
    }

    var localizedKey: LocalizedStringKey {
        switch self {
        case .idle:     return "Ready"
        case .scanning: return "Scanning"
        case .engaging: return "Targeting"
        case .killing:  return "Found!"
        }
    }
}

// MARK: - Vision Diagnostics

/// Phase A/B 使用的视觉链路诊断数据
struct VisionDiagnostics {
    var frameSize: CGSize = .zero
    var previewSize: CGSize = .zero
    var stage1CandidateCount: Int = 0
    var stableTargetCount: Int = 0
    var stage1ProcessingTime: TimeInterval = 0
    var stage2ProcessingTime: TimeInterval = 0
    var currentZoomFactor: CGFloat = 1.0
    var isApproaching = false
    var isStage2Active = false
    var centerTargetDistance: CGFloat?
    var activeTriggers: [String] = []
    var lastClassification: ClassificationResult?
    var lastUpdated = Date()

    var hasMeasurements: Bool {
        frameSize != .zero || stage1CandidateCount > 0 || stableTargetCount > 0 || lastClassification != nil
    }

    var stage1TimingText: String {
        String(format: "%.0fms", stage1ProcessingTime * 1000)
    }

    var stage2TimingText: String {
        stage2ProcessingTime > 0 ? String(format: "%.0fms", stage2ProcessingTime * 1000) : "--"
    }

    var centerDistanceText: String {
        guard let centerTargetDistance else { return "--" }
        return String(format: "%.0fpx", centerTargetDistance)
    }

    var triggerText: String {
        activeTriggers.isEmpty ? "--" : activeTriggers.joined(separator: "|")
    }
}

// MARK: - Detection Settings

/// 检测配置
struct DetectionSettings {
    /// Stage 1 置信度阈值 (低阈值 = 高召回率)
    var stage1Threshold: Float = 0.1
    
    /// Stage 2 置信度阈值 (高阈值 = 高精度)
    var stage2Threshold: Float = 0.7
    
    /// 触发 Stage 2 的最小目标像素
    var minTargetPixels: CGFloat = 50
    
    /// 触发 Stage 2 的最小变焦倍数
    var minZoomForStage2: CGFloat = 3.0
    
    /// 中心区域占屏幕比例
    var centerRegionRatio: CGFloat = 0.3
    
    /// 目标追踪超时帧数
    var trackingTimeoutFrames: Int = 30
    
    /// 是否启用手电筒
    var flashlightEnabled: Bool = true
    
    /// 是否启用震动反馈
    var hapticsEnabled: Bool = true
}
