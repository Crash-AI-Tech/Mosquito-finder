//
//  HuntingViewModel.swift
//  Mosquito-finder
//
//  狩猎视图模型 - 连接 UI 和业务逻辑
//

import Foundation
import Combine
import CoreVideo
import CoreMedia
import UIKit

/// 狩猎视图模型
@MainActor
class HuntingViewModel: ObservableObject {
    
    // MARK: - Published Properties (UI State)
    
    @Published var isSessionActive = false
    @Published var currentPhase: HuntingPhase = .idle
    @Published var trackedTargets: [TrackedTarget] = []
    @Published var activeTarget: TrackedTarget?
    @Published var classificationResult: ClassificationResult?
    @Published var guidanceState: GuidanceState = .scanning
    @Published var guidanceTarget: TrackedTarget?
    @Published var diagnostics = VisionDiagnostics()

    /// 发现蚊子时的冻结帧
    @Published var frozenFrame: UIImage?
    /// 冻结帧中蛊子的边界框（像素坐标）
    @Published var frozenTargetRect: CGRect?
    
    @Published var currentZoomFactor: CGFloat = 1.0
    @Published var isFlashlightOn = false
    @Published var isFocusLocked = false
    @Published var nativeImageSize: CGSize = CGSize(width: 1080, height: 1920) // 默认 1080P
    
    // Statistics
    @Published var sessionDuration: String = "00:00"
    @Published var mosquitoesFound: Int = 0
    
    // Error handling
    @Published var errorMessage: String?
    
    // MARK: - Dependencies
    
    let cameraController: CameraController
    let flashlightManager: FlashlightManager
    let hapticsEngine: HapticsEngine
    let motionDetector: MotionDetector
    let stateManager: HuntingStateManager
    let targetCoordinator: TargetCoordinator
    let statsStore: HuntingStatsStore
    
    // MARK: - Private Properties
    
    private var cancellables = Set<AnyCancellable>()
    private var sessionTimer: Timer?
    private var lastHapticTime = Date.distantPast
    private var lastFocusAssistTime = Date.distantPast
    
    // MARK: - Init
    
    init() {
        self.cameraController = CameraController()
        self.flashlightManager = FlashlightManager()
        self.hapticsEngine = HapticsEngine()
        self.motionDetector = MotionDetector()
        self.stateManager = HuntingStateManager()
        self.targetCoordinator = TargetCoordinator()
        self.statsStore = HuntingStatsStore.shared
        
        setupBindings()
        setupCameraFrameHandler()
    }
    
    // MARK: - Public Methods
    
    /// 开始狩猎会话
    func startHunting() {
        // 请求相机权限并在配置完成后启动，避免固定延迟导致的假启动和卡顿
        cameraController.requestAccessAndConfigure { [weak self] success in
            guard let self = self, success else { return }

            self.cameraController.start()
            self.motionDetector.start()
            self.stateManager.startSession()
            self.statsStore.beginSession()

            self.isSessionActive = true
            self.startSessionTimer()
        }
    }
    
    /// 停止狩猎会话
    func stopHunting() {
        let suspectsFound = stateManager.totalSuspectsFound
        let confirmedMosquitoes = stateManager.mosquitoesConfirmed
        let modelMode = RuntimeDetectionSettings.current.modelMode
        cameraController.stop()
        flashlightManager.turnOff()
        motionDetector.stop()
        stateManager.endSession()
        statsStore.endSession(
            suspectsFound: suspectsFound,
            confirmedMosquitoes: confirmedMosquitoes,
            modelMode: modelMode
        )
        targetCoordinator.reset()
        
        isSessionActive = false
        stopSessionTimer()
    }
    
    /// 设置变焦
    func setZoom(_ factor: CGFloat) {
        cameraController.setZoom(factor)
    }

    /// 同步相机预览尺寸，用于统一触发器和覆盖层坐标系
    func updatePreviewSize(_ size: CGSize) {
        guard size.width > 0, size.height > 0 else { return }
        targetCoordinator.screenSize = size
    }
    
    /// 切换闪光灯
    func toggleFlashlight() {
        flashlightManager.toggle()
    }
    
    /// 锁定/解锁对焦
    func toggleFocusLock() {
        if isFocusLocked {
            cameraController.unlockFocus()
        } else {
            cameraController.lockFocusOnCenter()
        }
    }
    
    /// 手动确认目标
    func confirmTarget(_ target: TrackedTarget) {
        stateManager.engageTarget(target)
        hapticsEngine.targetEngaging()
    }
    
    /// 关闭目标（点击已处理）
    func dismissTarget(_ target: TrackedTarget) {
        saveReviewCandidate(reason: "dismiss_target_button", targetID: target.id.uuidString)
        targetCoordinator.dismissTarget(target.id)
        hapticsEngine.targetDismissed()
        frozenFrame = nil
        frozenTargetRect = nil
        targetCoordinator.isPaused = false
        if stateManager.currentPhase == .killing || stateManager.currentPhase == .engaging {
            stateManager.targetHandled()
        }
    }

    /// 点击已处理（无需 target 对象）
    func dismissCurrentMosquito() {
        saveReviewCandidate(reason: "dismiss_current_button", targetID: activeTarget?.id.uuidString)
        hapticsEngine.targetDismissed()
        frozenFrame = nil
        frozenTargetRect = nil
        targetCoordinator.isPaused = false
        stateManager.targetHandled()
    }
    
    // MARK: - Private Methods
    
    private func setupBindings() {
        // 相机状态
        cameraController.$currentZoomFactor
            .receive(on: DispatchQueue.main)
            .assign(to: &$currentZoomFactor)
        
        cameraController.$isFocusLocked
            .receive(on: DispatchQueue.main)
            .assign(to: &$isFocusLocked)
        
        cameraController.$error
            .receive(on: DispatchQueue.main)
            .compactMap { $0?.localizedDescription }
            .assign(to: &$errorMessage)
        
        // 闪光灯状态
        flashlightManager.$isOn
            .receive(on: DispatchQueue.main)
            .assign(to: &$isFlashlightOn)
        
        // 狩猎状态
        stateManager.$currentPhase
            .receive(on: DispatchQueue.main)
            .assign(to: &$currentPhase)

        // 进入 killing 阶段时：冻结处理 + 抓屏
        stateManager.$currentPhase
            .receive(on: DispatchQueue.main)
            .sink { [weak self] phase in
                guard let self = self else { return }
                if phase == .killing && self.frozenFrame == nil {
                    self.targetCoordinator.isPaused = true
                    self.frozenFrame = self.cameraController.captureSnapshot()
                    // 直接从 stateManager 读取，避免 Combine 时序问题
                    self.frozenTargetRect = self.stateManager.activeTarget?.boundingBox
                }
            }
            .store(in: &cancellables)
        
        stateManager.$activeTarget
            .receive(on: DispatchQueue.main)
            .assign(to: &$activeTarget)
        
        stateManager.$mosquitoesConfirmed
            .receive(on: DispatchQueue.main)
            .assign(to: &$mosquitoesFound)
        
        // 目标追踪
        targetCoordinator.$trackedTargets
            .receive(on: DispatchQueue.main)
            .sink { [weak self] targets in
                guard let self = self else { return }
                
                // 同步相机设备给手电筒（协助处理多摄像头切换后的 Torch 引用）
                self.flashlightManager.updateDevice(self.cameraController.captureDevice)
                
                // 仅当发现新增的稳定目标，且距离上次震动超过 2.0 秒时才震动
                let now = Date()
                if targets.count > self.trackedTargets.count && now.timeIntervalSince(self.lastHapticTime) > 2.0 {
                    self.hapticsEngine.suspectDetected()
                    self.lastHapticTime = now
                }
                
                self.trackedTargets = targets

                if let activeID = self.activeTarget?.id,
                   let refreshedTarget = targets.first(where: { $0.id == activeID }) {
                    self.stateManager.syncActiveTarget(refreshedTarget)
                }
            }
            .store(in: &cancellables)

        targetCoordinator.$activeStage2Target
            .receive(on: DispatchQueue.main)
            .sink { [weak self] target in
                guard let self = self else { return }
                self.stateManager.syncActiveTarget(target)
            }
            .store(in: &cancellables)
        
        targetCoordinator.$currentClassification
            .receive(on: DispatchQueue.main)
            .sink { [weak self] result in
                guard let self = self, let result = result else { return }
                
                self.classificationResult = result
                self.stateManager.confirmClassification(result)
                
                if result.isMosquito {
                    self.statsStore.recordMosquito(
                        confidence: result.confidence,
                        modelMode: RuntimeDetectionSettings.current.modelMode
                    )
                    self.hapticsEngine.mosquitoConfirmed()
                } else {
                    self.hapticsEngine.targetDismissed()
                }
            }
            .store(in: &cancellables)

        targetCoordinator.$guidanceState
            .receive(on: DispatchQueue.main)
            .assign(to: &$guidanceState)

        targetCoordinator.$guidanceTarget
            .receive(on: DispatchQueue.main)
            .sink { [weak self] target in
                guard let self = self else { return }
                self.guidanceTarget = target
                self.assistFocusIfNeeded(target)
            }
            .store(in: &cancellables)

        targetCoordinator.$diagnostics
            .receive(on: DispatchQueue.main)
            .assign(to: &$diagnostics)
    }
    
    private func setupCameraFrameHandler() {
        cameraController.onFrameCaptured = { [weak self] sampleBuffer in
            guard let self = self else { return }
            
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
            
            // 首次获取原始尺寸
            let width = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
            let height = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
            let size = CGSize(width: width, height: height)
            
            DispatchQueue.main.async {
                if self.nativeImageSize != size {
                    self.nativeImageSize = size
                }
            }
            
            // 手机抖动时跳过分析（减少误报，节省电量），同时给用户明确的纠偏提示。
            if self.motionDetector.isShaking {
                self.targetCoordinator.setTransientGuidance(.holdStill)
                return
            }
            
            // 直接在相机串行回调队列处理，避免并发帧导致的追踪与状态错乱
            self.targetCoordinator.processFrame(
                pixelBuffer,
                zoomFactor: self.currentZoomFactor,
                isApproaching: self.motionDetector.isApproaching
            )
        }
    }

    private func assistFocusIfNeeded(_ target: TrackedTarget?) {
        guard let target,
              target.isStable,
              guidanceState == .centerCandidate || guidanceState == .zoomIn || guidanceState == .confirming else {
            return
        }

        let now = Date()
        guard now.timeIntervalSince(lastFocusAssistTime) > 1.2 else { return }
        lastFocusAssistTime = now

        let width = max(1, nativeImageSize.width)
        let height = max(1, nativeImageSize.height)
        cameraController.focusAndExpose(
            at: CGPoint(
                x: target.center.x / width,
                y: target.center.y / height
            )
        )
    }
    
    private func startSessionTimer() {
        sessionTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            DispatchQueue.main.async {
                self?.sessionDuration = self?.stateManager.formattedDuration ?? "00:00"
            }
        }
    }
    
    private func stopSessionTimer() {
        sessionTimer?.invalidate()
        sessionTimer = nil
    }

    private func saveReviewCandidate(reason: String, targetID: String?) {
        guard let frozenFrame,
              let imageData = frozenFrame.jpegData(compressionQuality: 0.92) else {
            return
        }

        let timestamp = ISO8601DateFormatter()
            .string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        let targetRect = frozenTargetRect
        let zoomFactor = currentZoomFactor
        let classification = classificationResult

        DispatchQueue.global(qos: .utility).async {
            let fileManager = FileManager.default
            guard let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first else {
                return
            }

            let outputDirectory = documents
                .appendingPathComponent("MosquitoFinderReview", isDirectory: true)
                .appendingPathComponent("candidate_hard_negative", isDirectory: true)
            do {
                try fileManager.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

                let imageURL = outputDirectory.appendingPathComponent("\(timestamp).jpg")
                try imageData.write(to: imageURL, options: .atomic)

                var metadata: [String: Any] = [
                    "label": "candidate_hard_negative",
                    "reason": reason,
                    "image_file": imageURL.lastPathComponent,
                    "created_at": timestamp,
                    "zoom_factor": Double(zoomFactor),
                    "model_confidence": Double(classification?.confidence ?? 0),
                    "model_is_mosquito": classification?.isMosquito ?? false
                ]

                if let targetID {
                    metadata["target_id"] = targetID
                }
                if let targetRect {
                    metadata["target_rect"] = [
                        "x": Double(targetRect.origin.x),
                        "y": Double(targetRect.origin.y),
                        "width": Double(targetRect.width),
                        "height": Double(targetRect.height)
                    ]
                }

                let metadataData = try JSONSerialization.data(
                    withJSONObject: metadata,
                    options: [.prettyPrinted, .sortedKeys]
                )
                let metadataURL = outputDirectory.appendingPathComponent("\(timestamp).json")
                try metadataData.write(to: metadataURL, options: .atomic)
            } catch {
                print("保存误报候选样本失败: \(error)")
            }
        }
    }
}
