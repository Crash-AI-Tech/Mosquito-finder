//
//  TargetCoordinator.swift
//  Mosquito-finder
//
//  目标协调器 - 协调 Stage 1、Tracker、Stage 2 的工作
//

import Foundation
import Combine
import UIKit
import CoreVideo
import CoreGraphics

/// 目标协调器
/// 负责协调各视觉组件的工作流程
class TargetCoordinator: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var suspectRegions: [SuspectRegion] = []
    @Published var trackedTargets: [TrackedTarget] = []
    @Published var currentClassification: ClassificationResult?
    @Published var isStage2Active = false
    @Published var activeStage2Target: TrackedTarget?
    @Published var guidanceState: GuidanceState = .scanning
    @Published var guidanceTarget: TrackedTarget?
    @Published var diagnostics = VisionDiagnostics()
    
    // MARK: - Dependencies
    
    let candidateSearchEngine: CandidateSearchEngine
    let objectTracker: ObjectTracker
    let stage2Classifier: Stage2Classifier
    var triggerEvaluator: TriggerEvaluator
    
    // MARK: - Configuration
    
    /// 屏幕尺寸，由调用者设置
    var screenSize: CGSize = CGSize(width: 390, height: 844)  // 默认值，运行时会更新

    /// 是否暂停处理（发现蚊子后暂停）
    var isPaused: Bool = false
    
    // MARK: - Private Properties
    
    private var cancellables = Set<AnyCancellable>()
    private var lastStage2Time: Date?
    private var stage2Cooldown: TimeInterval = 0.5  // Stage 2 最小间隔
    private var lockedGuidanceTargetID: UUID?
    private var guidanceLockExpiresAt = Date.distantPast
    private let guidanceLockDuration: TimeInterval = 1.55
    private let guidanceSwitchScoreMargin = 0.32
    private let guidanceWarmupFrames = 2
    private var suppressedGuidanceRegions: [SuppressedGuidanceRegion] = []
    private let negativeSuppressionDuration: TimeInterval = 3.0
    
    // MARK: - Init
    
    init() {
        self.candidateSearchEngine = CandidateSearchEngine()
        self.objectTracker = ObjectTracker()
        self.stage2Classifier = Stage2Classifier()
        self.triggerEvaluator = TriggerEvaluator(settings: RuntimeDetectionSettings.current)
        
        setupBindings()
    }
    
    // MARK: - Public Methods
    
    /// 处理新的视频帧
    func processFrame(_ pixelBuffer: CVPixelBuffer, zoomFactor: CGFloat, isApproaching: Bool) {
        // 发现蚊子后暂停处理
        guard !isPaused else { return }
        applyRuntimeSettings()
        let stage1StartTime = Date()

        // Stage 1: candidate search only. This does not mean "mosquito found".
        let detections = candidateSearchEngine.search(pixelBuffer: pixelBuffer)

        let stage1ProcessingTime = Date().timeIntervalSince(stage1StartTime)
        let frameSize = CGSize(
            width: CVPixelBufferGetWidth(pixelBuffer),
            height: CVPixelBufferGetHeight(pixelBuffer)
        )
        
        DispatchQueue.main.async {
            self.suspectRegions = detections
        }
        
        // 更新追踪
        objectTracker.update(with: detections, in: pixelBuffer)

        let stableTargetCount = objectTracker.stableTargets.count
        // 关键修复：用缓冲区尺寸（像素坐标）而非屏幕尺寸（点坐标）做中心判断
        // 屏幕中心约(195,422)pts ≠ 缓冲区中心(540,960)px，混用导致红框始终在左上角
        let centerTarget = objectTracker.getTargetNearCenter(screenSize: frameSize)
        let centerTargetDistance = centerTarget.map {
            triggerEvaluator.distanceToCenter(target: $0, screenSize: frameSize)
        }
        let activeTriggers = centerTarget.map {
            triggerEvaluator.getActiveTriggers(
                target: $0,
                zoomFactor: zoomFactor,
                isApproaching: isApproaching,
                screenSize: frameSize
            )
        } ?? []

        DispatchQueue.main.async {
            self.diagnostics = VisionDiagnostics(
                frameSize: frameSize,
                previewSize: self.screenSize,
                stage1CandidateCount: detections.count,
                stableTargetCount: stableTargetCount,
                stage1ProcessingTime: stage1ProcessingTime,
                stage2ProcessingTime: self.diagnostics.stage2ProcessingTime,
                currentZoomFactor: zoomFactor,
                isApproaching: isApproaching,
                isStage2Active: self.isStage2Active,
                centerTargetDistance: centerTargetDistance,
                activeTriggers: activeTriggers,
                lastClassification: self.diagnostics.lastClassification,
                lastUpdated: Date()
            )
        }

        updateGuidanceState(
            detections: detections,
            frameSize: frameSize,
            zoomFactor: zoomFactor,
            isApproaching: isApproaching
        )
        
        // 检查是否需要触发 Stage 2
        checkStage2Trigger(pixelBuffer: pixelBuffer, frameSize: frameSize, zoomFactor: zoomFactor, isApproaching: isApproaching)
    }

    func setTransientGuidance(_ state: GuidanceState) {
        DispatchQueue.main.async {
            self.guidanceState = state
        }
    }
    
    /// 手动触发 Stage 2 分类
    func manualClassify(target: TrackedTarget, in pixelBuffer: CVPixelBuffer) {
        performStage2Classification(target: target, in: pixelBuffer)
    }
    
    /// 更新目标状态
    func updateTargetState(_ id: UUID, state: TargetState) {
        objectTracker.updateTargetState(id, state: state)
        
        DispatchQueue.main.async {
            self.trackedTargets = self.objectTracker.trackedTargets
        }
    }
    
    /// 移除目标
    func dismissTarget(_ id: UUID) {
        objectTracker.removeTarget(id)
        
        DispatchQueue.main.async {
            if self.activeStage2Target?.id == id {
                self.activeStage2Target = nil
            }
            if self.lockedGuidanceTargetID == id {
                self.lockedGuidanceTargetID = nil
                self.guidanceLockExpiresAt = .distantPast
                self.guidanceTarget = nil
            }
            self.trackedTargets = self.objectTracker.trackedTargets
            if self.isStage2Active {
                self.isStage2Active = false
            }
        }
    }
    
    /// 重置所有状态
    func reset() {
        isPaused = false
        objectTracker.reset()
        
        DispatchQueue.main.async {
            self.suspectRegions = []
            self.trackedTargets = []
            self.currentClassification = nil
            self.isStage2Active = false
            self.activeStage2Target = nil
            self.guidanceState = .scanning
            self.guidanceTarget = nil
        }

        lockedGuidanceTargetID = nil
        guidanceLockExpiresAt = .distantPast
        suppressedGuidanceRegions = []
    }
    
    // MARK: - Private Methods

    private func applyRuntimeSettings() {
        let settings = RuntimeDetectionSettings.current
        candidateSearchEngine.modelMode = settings.modelMode
        candidateSearchEngine.maxCandidates = settings.maxStage1Detections
        // Stage 1 is intentionally high-recall. It emits candidate regions only;
        // high-resolution Stage 2 crop classification makes the final decision.
        candidateSearchEngine.detectorCandidateThreshold = settings.modelMode.isDetectorMode
            ? min(0.24, max(0.08, settings.stage2ConfidenceThreshold * 0.42))
            : 0.35
        candidateSearchEngine.detectorNmsIouThreshold = settings.detectorNmsIouThreshold
        candidateSearchEngine.localContrastThreshold = settings.stage1LocalContrastThreshold
        candidateSearchEngine.backgroundVarianceThreshold = settings.stage1BackgroundVarianceThreshold
        candidateSearchEngine.frameInterval = settings.modelMode.isDetectorMode ? 0.16 : 0.11
        candidateSearchEngine.candidateClassifierEnabled = true
        candidateSearchEngine.candidateClassifierWeight = settings.modelMode.isDetectorMode ? 0.22 : 0.28
        objectTracker.requiredStableFrames = settings.stableFrameCount
        objectTracker.useVisionTracking = !settings.modelMode.isDetectorMode
        stage2Classifier.apply(settings: settings)
        triggerEvaluator.apply(settings: settings)
        stage2Cooldown = settings.stage2Cooldown
    }
    
    private func setupBindings() {
        // 监听追踪器更新
        objectTracker.$trackedTargets
            .receive(on: DispatchQueue.main)
            .sink { [weak self] targets in
                guard let self = self else { return }

                self.trackedTargets = targets.filter { $0.isStable }

                if let activeID = self.activeStage2Target?.id {
                    if let refreshedTarget = targets.first(where: { $0.id == activeID }) {
                        self.activeStage2Target = refreshedTarget
                    } else if !self.isStage2Active {
                        self.activeStage2Target = nil
                    }
                }
            }
            .store(in: &cancellables)
    }
    
    private func checkStage2Trigger(pixelBuffer: CVPixelBuffer, frameSize: CGSize, zoomFactor: CGFloat, isApproaching: Bool) {
        // 检查冷却时间
        if let lastTime = lastStage2Time, Date().timeIntervalSince(lastTime) < stage2Cooldown {
            return
        }

        // 获取缓冲区中心附近的稳定目标
        // centerRadius 与 TriggerEvaluator.centerRegionRatio 保持一致，避免漏选
        let centerRadius = min(frameSize.width, frameSize.height) * CGFloat(triggerEvaluator.centerRegionRatio)
        guard let centerTarget = objectTracker.getTargetNearCenter(screenSize: frameSize, centerRadius: centerRadius),
              centerTarget.isStable else {
            return
        }
        
        // 评估触发条件（使用 frameSize = buffer 像素坐标系）
        let shouldTrigger = triggerEvaluator.shouldActivateStage2(
            target: centerTarget,
            zoomFactor: zoomFactor,
            isApproaching: isApproaching,
            screenSize: frameSize
        )
        
        if shouldTrigger {
            performStage2Classification(target: centerTarget, in: pixelBuffer)
        }
    }

    private func performStage2Classification(target: TrackedTarget, in pixelBuffer: CVPixelBuffer) {
        lastStage2Time = Date()
        
        DispatchQueue.main.async {
            self.isStage2Active = true
            self.updateTargetState(target.id, state: .engaging)
            self.activeStage2Target = self.objectTracker.trackedTargets.first(where: { $0.id == target.id }) ?? target
        }
        
        let settings = RuntimeDetectionSettings.current
        let frameSize = CGSize(
            width: CVPixelBufferGetWidth(pixelBuffer),
            height: CVPixelBufferGetHeight(pixelBuffer)
        )
        let confirmationRegion = expandedConfirmationRegion(
            around: target.boundingBox,
            in: frameSize,
            mode: settings.modelMode
        )
        let result = stage2Classifier.classify(region: confirmationRegion, in: pixelBuffer)
        
        DispatchQueue.main.async {
            self.currentClassification = result
            self.activeStage2Target = self.objectTracker.trackedTargets.first(where: { $0.id == target.id }) ?? self.activeStage2Target
            self.guidanceState = result.isMosquito ? .confirmed : .scanning

            var updatedDiagnostics = self.diagnostics
            updatedDiagnostics.stage2ProcessingTime = result.processingTime
            updatedDiagnostics.isStage2Active = false
            updatedDiagnostics.lastClassification = result
            updatedDiagnostics.lastUpdated = Date()
            self.diagnostics = updatedDiagnostics
            
            // 更新目标状态
            let newState: TargetState = result.isMosquito ? .confirmed : .dismissed
            self.updateTargetState(target.id, state: newState)
            
            // 如果不是蚊子，延迟移除
            if !result.isMosquito {
                let suppressionRect = self.expandedConfirmationRegion(
                    around: target.boundingBox,
                    in: frameSize,
                    mode: settings.modelMode
                )
                self.suppressedGuidanceRegions.append(
                    SuppressedGuidanceRegion(
                        rect: suppressionRect,
                        expiresAt: Date().addingTimeInterval(self.negativeSuppressionDuration)
                    )
                )
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                    self.dismissTarget(target.id)
                }
            }
            
            self.isStage2Active = false
        }
    }

    private func updateGuidanceState(
        detections: [SuspectRegion],
        frameSize: CGSize,
        zoomFactor: CGFloat,
        isApproaching: Bool
    ) {
        let candidate = bestGuidanceTarget(frameSize: frameSize)
        let nextState: GuidanceState

        if isStage2Active {
            nextState = .confirming
        } else if let candidate {
            let triggers = triggerEvaluator.getActiveTriggers(
                target: candidate,
                zoomFactor: zoomFactor,
                isApproaching: isApproaching,
                screenSize: frameSize
            )

            if !candidate.isStable {
                nextState = .candidateFound
            } else if !triggers.contains("center") {
                nextState = .centerCandidate
            } else if !triggers.contains("zoom") || !triggers.contains("size") {
                nextState = .zoomIn
            } else {
                nextState = .confirming
            }
        } else {
            nextState = detections.isEmpty ? .noSignal : .scanning
        }

        DispatchQueue.main.async {
            self.guidanceState = nextState
            self.guidanceTarget = candidate
        }
    }

    private func bestGuidanceTarget(frameSize: CGSize) -> TrackedTarget? {
        let now = Date()
        pruneSuppressedGuidanceRegions(now: now)

        let candidates = objectTracker.trackedTargets.filter {
            $0.state != .dismissed
                && $0.visibility > 0.15
                && !$0.isStale
                && $0.detectedFrameCount >= guidanceWarmupFrames
                && !isSuppressed($0.boundingBox, now: now)
        }

        guard !candidates.isEmpty else {
            lockedGuidanceTargetID = nil
            guidanceLockExpiresAt = .distantPast
            return nil
        }

        let ranked = candidates.sorted {
            guidanceScore(for: $0, frameSize: frameSize) > guidanceScore(for: $1, frameSize: frameSize)
        }
        guard let best = ranked.first else { return nil }

        if let lockedID = lockedGuidanceTargetID,
           let lockedTarget = candidates.first(where: { $0.id == lockedID }) {
            let lockedScore = guidanceScore(for: lockedTarget, frameSize: frameSize)
            let bestScore = guidanceScore(for: best, frameSize: frameSize)

            if now < guidanceLockExpiresAt || bestScore < lockedScore + guidanceSwitchScoreMargin {
                guidanceLockExpiresAt = now.addingTimeInterval(guidanceLockDuration)
                return lockedTarget
            }
        }

        lockedGuidanceTargetID = best.id
        guidanceLockExpiresAt = now.addingTimeInterval(guidanceLockDuration)
        return best
    }

    private func guidanceScore(for target: TrackedTarget, frameSize: CGSize) -> Double {
        let frameCenter = CGPoint(x: frameSize.width / 2, y: frameSize.height / 2)
        let centerDistance = hypot(target.center.x - frameCenter.x, target.center.y - frameCenter.y)
        let centerRange = max(1, min(frameSize.width, frameSize.height) * 0.72)
        let centerScore = Double(1.0 - min(1.0, centerDistance / centerRange))
        let stableProgress = min(1.0, Double(target.detectedFrameCount) / Double(max(1, target.requiredStableFrames + 1)))
        let freshness = max(0.0, 1.0 - Double(target.framesMissed) / 5.0)
        let confidence = min(1.0, max(0.0, Double(target.trackingConfidence)))
        let lockBonus = target.id == lockedGuidanceTargetID ? 0.35 : 0.0

        return confidence * 0.24
            + centerScore * 0.24
            + stableProgress * 0.36
            + freshness * 0.16
            + lockBonus
    }

    private func pruneSuppressedGuidanceRegions(now: Date) {
        suppressedGuidanceRegions.removeAll { $0.expiresAt <= now }
    }

    private func isSuppressed(_ rect: CGRect, now: Date) -> Bool {
        pruneSuppressedGuidanceRegions(now: now)
        return suppressedGuidanceRegions.contains {
            $0.rect.intersects(rect) || $0.rect.contains(CGPoint(x: rect.midX, y: rect.midY))
        }
    }

    private func expandedConfirmationRegion(
        around box: CGRect,
        in frameSize: CGSize,
        mode: RuntimeModelMode
    ) -> CGRect {
        let multiplier: CGFloat = mode.isDetectorMode ? 3.8 : 2.8
        let minSide: CGFloat = mode.isDetectorMode ? 224 : 160
        let side = max(max(box.width, box.height) * multiplier, minSide)
        let centered = CGRect(
            x: box.midX - side / 2,
            y: box.midY - side / 2,
            width: side,
            height: side
        )
        return clamp(centered, to: frameSize)
    }

    private func clamp(_ rect: CGRect, to size: CGSize) -> CGRect {
        let width = min(rect.width, size.width)
        let height = min(rect.height, size.height)
        let x = min(max(rect.origin.x, 0), max(0, size.width - width))
        let y = min(max(rect.origin.y, 0), max(0, size.height - height))
        return CGRect(x: x, y: y, width: width, height: height)
    }
}

private struct SuppressedGuidanceRegion {
    let rect: CGRect
    let expiresAt: Date
}
