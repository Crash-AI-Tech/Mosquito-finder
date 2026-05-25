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
    @Published var diagnostics = VisionDiagnostics()
    
    // MARK: - Dependencies
    
    let stage1Detector: Stage1Detector
    let objectTracker: ObjectTracker
    let stage2Classifier: Stage2Classifier
    let triggerEvaluator: TriggerEvaluator
    
    // MARK: - Configuration
    
    /// 屏幕尺寸，由调用者设置
    var screenSize: CGSize = CGSize(width: 390, height: 844)  // 默认值，运行时会更新

    /// 是否暂停处理（发现蚊子后暂停）
    var isPaused: Bool = false
    
    // MARK: - Private Properties
    
    private var cancellables = Set<AnyCancellable>()
    private var lastStage2Time: Date?
    private let stage2Cooldown: TimeInterval = 0.5  // Stage 2 最小间隔
    
    // MARK: - Init
    
    init() {
        self.stage1Detector = Stage1Detector()
        self.objectTracker = ObjectTracker()
        self.stage2Classifier = Stage2Classifier()
        self.triggerEvaluator = TriggerEvaluator()
        
        setupBindings()
    }
    
    // MARK: - Public Methods
    
    /// 处理新的视频帧
    func processFrame(_ pixelBuffer: CVPixelBuffer, zoomFactor: CGFloat, isApproaching: Bool) {
        // 发现蚊子后暂停处理
        guard !isPaused else { return }
        let stage1StartTime = Date()

        // Stage 1: 雷达扫描 - 检测暗点
        let detections = stage1Detector.detectDarkSpots(pixelBuffer: pixelBuffer)

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
        let centerTarget = objectTracker.getTargetNearCenter(screenSize: screenSize)
        let centerTargetDistance = centerTarget.map {
            triggerEvaluator.distanceToCenter(target: $0, screenSize: screenSize)
        }
        let activeTriggers = centerTarget.map {
            triggerEvaluator.getActiveTriggers(
                target: $0,
                zoomFactor: zoomFactor,
                isApproaching: isApproaching,
                screenSize: screenSize
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
        
        // 检查是否需要触发 Stage 2
        checkStage2Trigger(pixelBuffer: pixelBuffer, zoomFactor: zoomFactor, isApproaching: isApproaching)
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
        }
    }
    
    // MARK: - Private Methods
    
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
    
    private func checkStage2Trigger(pixelBuffer: CVPixelBuffer, zoomFactor: CGFloat, isApproaching: Bool) {
        // 检查冷却时间
        if let lastTime = lastStage2Time, Date().timeIntervalSince(lastTime) < stage2Cooldown {
            return
        }
        
        // 获取中心附近的目标
        guard let centerTarget = objectTracker.getTargetNearCenter(screenSize: screenSize) else {
            return
        }
        
        // 评估触发条件
        let shouldTrigger = triggerEvaluator.shouldActivateStage2(
            target: centerTarget,
            zoomFactor: zoomFactor,
            isApproaching: isApproaching,
            screenSize: screenSize
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
        
        // 执行分类
        let result = stage2Classifier.classify(region: target.boundingBox, in: pixelBuffer)
        
        DispatchQueue.main.async {
            self.currentClassification = result
            self.activeStage2Target = self.objectTracker.trackedTargets.first(where: { $0.id == target.id }) ?? self.activeStage2Target

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
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                    self.dismissTarget(target.id)
                }
            }
            
            self.isStage2Active = false
        }
    }
}
