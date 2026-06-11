//
//  Models.swift
//  Mosquito-finder
//
//  Core data models for the Two-Stage Detection system
//

import Foundation
import SwiftUI
import CoreGraphics

// MARK: - Runtime Detection Configuration

enum RuntimeModelMode: String, CaseIterable, Identifiable {
    case classic = "classic"
    case detectorDfine = "detector_dfine"
    case detectorYolox = "detector_yolox"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .classic: return "Classic"
        case .detectorDfine: return "D-FINE"
        case .detectorYolox: return "YOLOX"
        }
    }

    var localizedDisplayNameKey: LocalizedStringKey {
        switch self {
        case .classic: return "Classic"
        case .detectorDfine: return "D-FINE"
        case .detectorYolox: return "YOLOX"
        }
    }

    var isDetectorMode: Bool {
        self == .detectorDfine || self == .detectorYolox
    }

    var bundledModelName: String? {
        switch self {
        case .detectorDfine: return "DfineMosquitoDetector"
        case .detectorYolox: return "YoloxMosquitoDetector"
        default: return nil
        }
    }

    var isBundled: Bool {
        guard let name = bundledModelName else { return true }
        return Bundle.main.url(forResource: name, withExtension: "mlmodelc") != nil
            || Bundle.main.url(forResource: name, withExtension: "mlmodel") != nil
    }

    var isProductionReady: Bool {
        switch self {
        case .classic, .detectorDfine, .detectorYolox:
            return true
        }
    }

    static var selectableCases: [RuntimeModelMode] {
        allCases.filter { $0.isBundled && $0.isProductionReady }
    }

    static var preferredDefault: RuntimeModelMode {
        if RuntimeModelMode.detectorDfine.isBundled {
            return .detectorDfine
        }
        return RuntimeModelMode.detectorYolox.isBundled ? .detectorYolox : .classic
    }

    static func fromStoredValue(_ value: String?) -> RuntimeModelMode {
        switch value {
        case RuntimeModelMode.detectorDfine.rawValue:
            return .detectorDfine
        case RuntimeModelMode.detectorYolox.rawValue:
            return .detectorYolox
        case RuntimeModelMode.classic.rawValue, "coreml_strict", "coreml_balanced":
            return .classic
        default:
            return .preferredDefault
        }
    }
}

enum ClassicDetectionPreset: String, CaseIterable, Identifiable {
    case balanced
    case strict

    var id: String { rawValue }

    var localizedTitleKey: LocalizedStringKey {
        switch self {
        case .balanced: return "Balanced"
        case .strict: return "Strict"
        }
    }

    var localizedDescriptionKey: LocalizedStringKey {
        switch self {
        case .balanced:
            return "Faster confirmation with moderate false-positive control."
        case .strict:
            return "Higher confirmation threshold for fewer false positives."
        }
    }

    static func fromStoredValue(_ value: String?) -> ClassicDetectionPreset {
        switch value {
        case ClassicDetectionPreset.strict.rawValue, "coreml_strict":
            return .strict
        default:
            return .balanced
        }
    }
}

struct RuntimeDetectionSettings {
    private static let dfineFullFrameSettingsVersion = 2

    var modelMode: RuntimeModelMode
    var stage2ConfidenceThreshold: Float
    var minZoomFactor: CGFloat
    var centerRegionRatio: CGFloat
    var minTargetSize: CGFloat
    var stableFrameCount: Int
    var stage2Cooldown: TimeInterval
    var maxStage1Detections: Int
    var stage1LocalContrastThreshold: Float
    var stage1BackgroundVarianceThreshold: Float
    var detectorNmsIouThreshold: CGFloat

    static let classicStrict = RuntimeDetectionSettings(
        modelMode: .classic,
        stage2ConfidenceThreshold: 0.90,
        minZoomFactor: 2.0,
        centerRegionRatio: 0.25,
        minTargetSize: 20,
        stableFrameCount: 5,
        stage2Cooldown: 0.5,
        maxStage1Detections: 5,
        stage1LocalContrastThreshold: 0.08,
        stage1BackgroundVarianceThreshold: 0.015,
        detectorNmsIouThreshold: 0.35
    )

    static let classicBalanced = RuntimeDetectionSettings(
        modelMode: .classic,
        stage2ConfidenceThreshold: 0.82,
        minZoomFactor: 1.5,
        centerRegionRatio: 0.30,
        minTargetSize: 18,
        stableFrameCount: 4,
        stage2Cooldown: 0.5,
        maxStage1Detections: 6,
        stage1LocalContrastThreshold: 0.07,
        stage1BackgroundVarianceThreshold: 0.018,
        detectorNmsIouThreshold: 0.35
    )

    static let strict = classicStrict
    static let balanced = classicBalanced

    static let yoloxHighPrecision = RuntimeDetectionSettings(
        modelMode: .detectorYolox,
        stage2ConfidenceThreshold: 0.70,
        minZoomFactor: 1.4,
        centerRegionRatio: 0.32,
        minTargetSize: 16,
        stableFrameCount: 4,
        stage2Cooldown: 0.45,
        maxStage1Detections: 8,
        stage1LocalContrastThreshold: 0.06,
        stage1BackgroundVarianceThreshold: 0.018,
        detectorNmsIouThreshold: 0.35
    )

    static let dfineHighPrecision = RuntimeDetectionSettings(
        modelMode: .detectorDfine,
        stage2ConfidenceThreshold: 0.50,
        minZoomFactor: 1.0,
        centerRegionRatio: 0.50,
        minTargetSize: 8,
        stableFrameCount: 2,
        stage2Cooldown: 0.25,
        maxStage1Detections: 8,
        stage1LocalContrastThreshold: 0.06,
        stage1BackgroundVarianceThreshold: 0.018,
        detectorNmsIouThreshold: 0.35
    )

    static func preset(for mode: RuntimeModelMode) -> RuntimeDetectionSettings {
        switch mode {
        case .classic:
            return classicBalanced
        case .detectorYolox:
            return yoloxHighPrecision
        case .detectorDfine:
            return dfineHighPrecision
        }
    }

    static func preset(forClassicPreset preset: ClassicDetectionPreset) -> RuntimeDetectionSettings {
        switch preset {
        case .balanced:
            return classicBalanced
        case .strict:
            return classicStrict
        }
    }

    static var current: RuntimeDetectionSettings {
        let defaults = UserDefaults.standard
        let storedMode = defaults.string(forKey: "detectionModelMode") ?? RuntimeModelMode.preferredDefault.rawValue
        var requestedMode = RuntimeModelMode.fromStoredValue(storedMode)

        if defaults.object(forKey: "classicDetectionPreset") == nil {
            if storedMode == "coreml_strict" {
                defaults.set(ClassicDetectionPreset.strict.rawValue, forKey: "classicDetectionPreset")
            } else if storedMode == "coreml_balanced" {
                defaults.set(ClassicDetectionPreset.balanced.rawValue, forKey: "classicDetectionPreset")
            }
        }

        if requestedMode == .detectorYolox,
           RuntimeModelMode.detectorDfine.isBundled,
           !defaults.bool(forKey: "didMigrateToDfineFullFrameDetector") {
            requestedMode = .detectorDfine
            defaults.set(true, forKey: "didMigrateToDfineFullFrameDetector")
            defaults.set(requestedMode.rawValue, forKey: "detectionModelMode")
        }

        if RuntimeModelMode.detectorDfine.isBundled,
           defaults.integer(forKey: "dfineFullFrameSettingsVersion") < dfineFullFrameSettingsVersion {
            requestedMode = .detectorDfine
            defaults.set(requestedMode.rawValue, forKey: "detectionModelMode")
        }

        let mode = requestedMode.isBundled && requestedMode.isProductionReady ? requestedMode : RuntimeModelMode.preferredDefault
        let preset = mode == .classic
            ? RuntimeDetectionSettings.preset(
                forClassicPreset: ClassicDetectionPreset.fromStoredValue(defaults.string(forKey: "classicDetectionPreset"))
            )
            : RuntimeDetectionSettings.preset(for: mode)

        if storedMode != mode.rawValue {
            defaults.set(mode.rawValue, forKey: "detectionModelMode")
        }

        if mode == .detectorDfine,
           defaults.integer(forKey: "dfineFullFrameSettingsVersion") < dfineFullFrameSettingsVersion {
            defaults.set(true, forKey: "didApplyDfineFullFrameSettings")
            defaults.set(dfineFullFrameSettingsVersion, forKey: "dfineFullFrameSettingsVersion")
            applyPreset(.detectorDfine)
        }

        return RuntimeDetectionSettings(
            modelMode: mode,
            stage2ConfidenceThreshold: Float(defaults.doubleOrDefault("stage2ConfidenceThreshold", Double(preset.stage2ConfidenceThreshold))),
            minZoomFactor: CGFloat(defaults.doubleOrDefault("minZoomFactor", Double(preset.minZoomFactor))),
            centerRegionRatio: CGFloat(defaults.doubleOrDefault("centerRegionRatio", Double(preset.centerRegionRatio))),
            minTargetSize: CGFloat(defaults.doubleOrDefault("minTargetSize", Double(preset.minTargetSize))),
            stableFrameCount: max(2, defaults.integerOrDefault("stableFrameCount", preset.stableFrameCount)),
            stage2Cooldown: defaults.doubleOrDefault("stage2Cooldown", preset.stage2Cooldown),
            maxStage1Detections: max(1, defaults.integerOrDefault("maxStage1Detections", preset.maxStage1Detections)),
            stage1LocalContrastThreshold: Float(defaults.doubleOrDefault("stage1LocalContrastThreshold", Double(preset.stage1LocalContrastThreshold))),
            stage1BackgroundVarianceThreshold: Float(defaults.doubleOrDefault("stage1BackgroundVarianceThreshold", Double(preset.stage1BackgroundVarianceThreshold))),
            detectorNmsIouThreshold: CGFloat(defaults.doubleOrDefault("detectorNmsIouThreshold", Double(preset.detectorNmsIouThreshold)))
        )
    }

    static func applyPreset(_ mode: RuntimeModelMode) {
        let preset = RuntimeDetectionSettings.preset(for: mode)
        if mode == .classic {
            UserDefaults.standard.set(ClassicDetectionPreset.balanced.rawValue, forKey: "classicDetectionPreset")
        }
        apply(preset)
    }

    static func applyClassicPreset(_ preset: ClassicDetectionPreset) {
        UserDefaults.standard.set(preset.rawValue, forKey: "classicDetectionPreset")
        apply(RuntimeDetectionSettings.preset(forClassicPreset: preset))
    }

    private static func apply(_ preset: RuntimeDetectionSettings) {
        let defaults = UserDefaults.standard
        defaults.set(preset.modelMode.rawValue, forKey: "detectionModelMode")
        defaults.set(Double(preset.stage2ConfidenceThreshold), forKey: "stage2ConfidenceThreshold")
        defaults.set(Double(preset.minZoomFactor), forKey: "minZoomFactor")
        defaults.set(Double(preset.centerRegionRatio), forKey: "centerRegionRatio")
        defaults.set(Double(preset.minTargetSize), forKey: "minTargetSize")
        defaults.set(preset.stableFrameCount, forKey: "stableFrameCount")
        defaults.set(preset.stage2Cooldown, forKey: "stage2Cooldown")
        defaults.set(preset.maxStage1Detections, forKey: "maxStage1Detections")
        defaults.set(Double(preset.stage1LocalContrastThreshold), forKey: "stage1LocalContrastThreshold")
        defaults.set(Double(preset.stage1BackgroundVarianceThreshold), forKey: "stage1BackgroundVarianceThreshold")
        defaults.set(Double(preset.detectorNmsIouThreshold), forKey: "detectorNmsIouThreshold")
        if preset.modelMode == .detectorDfine {
            defaults.set(dfineFullFrameSettingsVersion, forKey: "dfineFullFrameSettingsVersion")
        }
    }
}

private extension UserDefaults {
    func doubleOrDefault(_ key: String, _ defaultValue: Double) -> Double {
        object(forKey: key) == nil ? defaultValue : double(forKey: key)
    }

    func integerOrDefault(_ key: String, _ defaultValue: Int) -> Int {
        object(forKey: key) == nil ? defaultValue : integer(forKey: key)
    }
}

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
    var requiredStableFrames: Int = RuntimeDetectionSettings.strict.stableFrameCount
    
    init(
        id: UUID = UUID(),
        boundingBox: CGRect,
        trackingConfidence: Float = 1.0,
        state: TargetState = .suspect,
        lastUpdated: Date = Date(),
        detectedFrameCount: Int = 1,
        requiredStableFrames: Int = RuntimeDetectionSettings.strict.stableFrameCount,
        visibility: Double = 1.0
    ) {
        self.id = id
        self.boundingBox = boundingBox
        self.trackingConfidence = trackingConfidence
        self.state = state
        self.lastUpdated = lastUpdated
        self.detectedFrameCount = detectedFrameCount
        self.requiredStableFrames = requiredStableFrames
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
    
    /// 目标是否稳定。当前阶段优先压误报，要求目标连续出现约半秒。
    var isStable: Bool {
        detectedFrameCount >= requiredStableFrames
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
