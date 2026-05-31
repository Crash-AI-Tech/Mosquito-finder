//
//  ObjectTracker.swift
//  Mosquito-finder
//
//  目标追踪器 - 在帧间保持目标稳定
//

import Foundation
import Combine
import Vision
import CoreVideo
import CoreGraphics

/// 目标追踪器
/// 使用 Vision 框架的追踪能力保持目标锁定
class ObjectTracker: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var trackedTargets: [TrackedTarget] = []
    
    /// 仅包含稳定的目标 (用于 UI 显示)
    var stableTargets: [TrackedTarget] {
        trackedTargets.filter { $0.isStable }
    }
    
    @Published var isTracking = false
    
    // MARK: - Configuration
    
    /// IOU 阈值：判断新检测是否匹配已有目标
    var iouThreshold: Float = 0.3
    
    /// 目标最大生命周期（帧数）
    var maxLifetimeFrames: Int = 30
    
    /// 开启 Vision 追踪
    var useVisionTracking = true

    /// 判定稳定所需连续命中帧数
    var requiredStableFrames = RuntimeDetectionSettings.strict.stableFrameCount
    
    // MARK: - Private Properties
    
    private var trackingRequests: [UUID: VNTrackObjectRequest] = [:]
    private var lastObservations: [UUID: VNDetectedObjectObservation] = [:]
    private let sequenceHandler = VNSequenceRequestHandler()
    
    // MARK: - Public Methods
    
    /// 更新追踪：融合新检测结果
    func update(with detections: [SuspectRegion], in pixelBuffer: CVPixelBuffer) {
        isTracking = true
        defer { isTracking = false }
        for index in trackedTargets.indices {
            trackedTargets[index].requiredStableFrames = requiredStableFrames
        }
        
        let imageWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let imageHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
        
        // --- Phase 2.8: 背景锚定 ---
        compensateCameraMotion(in: pixelBuffer, imageSize: CGSize(width: imageWidth, height: imageHeight))
        
        // 1. 更新现有目标的追踪 (Vision Native)
        updateExistingTracks(in: pixelBuffer, imageSize: CGSize(width: imageWidth, height: imageHeight))
        
        // 2. 匹配新检测与现有目标
        var matchedDetectionIndices = Set<Int>()
        var matchedTargetIDs = Set<UUID>()
        
        for (index, detection) in detections.enumerated() {
            if let matchedTarget = findMatchingTarget(for: detection) {
                // 更新匹配的目标
                updateTarget(matchedTarget.id, with: detection)
                matchedDetectionIndices.insert(index)
                matchedTargetIDs.insert(matchedTarget.id)
            }
        }
        
        // 3. 处理丢失的目标 (持久化记忆)
        markMissedTargets(matchedTargetIDs: matchedTargetIDs)
        
        // 4. 为未匹配的检测创建新目标
        for (index, detection) in detections.enumerated() {
            if !matchedDetectionIndices.contains(index) {
                addNewTarget(from: detection, in: pixelBuffer, imageSize: CGSize(width: imageWidth, height: imageHeight))
            }
        }
        
        // 5. 清理过期目标
        cleanupStaleTargets()
        
        // 保存当前帧，供下一帧对位
        self.lastFramePixelBuffer = pixelBuffer
    }
    
    // MARK: - Private Context for Anchoring
    
    private var lastFramePixelBuffer: CVPixelBuffer?
    
    /// 补偿相机运动：将方框相对于背景固定
    private func compensateCameraMotion(in currentBuffer: CVPixelBuffer, imageSize: CGSize) {
        guard useVisionTracking else { return }
        guard let lastBuffer = lastFramePixelBuffer else { return }
        
        let registrationRequest = VNTranslationalImageRegistrationRequest(targetedCVPixelBuffer: currentBuffer)
        do {
            try sequenceHandler.perform([registrationRequest], on: lastBuffer)
            
            if let observation = registrationRequest.results?.first as? VNImageTranslationAlignmentObservation {
                let transform = observation.alignmentTransform
                
                // transform 是一个 CGAffineTransform，它描述了从 lastBuffer 到 currentBuffer 的位移
                // 为了让方框「钉」在墙上，我们需要把方框坐标也随之移动
                let tx = transform.tx
                let ty = -transform.ty // Vision 坐标系 Y 轴反转补偿
                
                for index in trackedTargets.indices {
                    let oldBox = trackedTargets[index].boundingBox
                    trackedTargets[index].boundingBox = oldBox.offsetBy(dx: tx, dy: ty)
                }
            }
        } catch {
            print("背景锚定计算失败: \(error)")
        }
    }
    
    /// 获取屏幕中心附近的目标
    func getTargetNearCenter(screenSize: CGSize, centerRadius: CGFloat = 100) -> TrackedTarget? {
        let screenCenter = CGPoint(x: screenSize.width / 2, y: screenSize.height / 2)
        
        return trackedTargets
            .filter { target in
                let distance = hypot(target.center.x - screenCenter.x, target.center.y - screenCenter.y)
                return distance < centerRadius
            }
            .sorted { target1, target2 in
                let d1 = hypot(target1.center.x - screenCenter.x, target1.center.y - screenCenter.y)
                let d2 = hypot(target2.center.x - screenCenter.x, target2.center.y - screenCenter.y)
                return d1 < d2
            }
            .first
    }
    
    /// 根据 ID 更新目标状态
    func updateTargetState(_ id: UUID, state: TargetState) {
        if let index = trackedTargets.firstIndex(where: { $0.id == id }) {
            trackedTargets[index].state = state
            trackedTargets[index].lastUpdated = Date()
        }
    }
    
    /// 移除目标
    func removeTarget(_ id: UUID) {
        trackedTargets.removeAll { $0.id == id }
        trackingRequests.removeValue(forKey: id)
        lastObservations.removeValue(forKey: id)
    }
    
    /// 清空所有目标
    func reset() {
        trackedTargets.removeAll()
        trackingRequests.removeAll()
        lastObservations.removeAll()
    }
    
    // MARK: - Private Methods
    
    private func updateExistingTracks(in pixelBuffer: CVPixelBuffer, imageSize: CGSize) {
        guard useVisionTracking else { return }
        
        for (id, request) in trackingRequests {
            do {
                try sequenceHandler.perform([request], on: pixelBuffer)
                
                if let observation = request.results?.first as? VNDetectedObjectObservation {
                    // 更新目标位置
                    let box = observation.boundingBox
                    let rect = CGRect(
                        x: box.origin.x * imageSize.width,
                        y: (1 - box.origin.y - box.height) * imageSize.height,
                        width: box.width * imageSize.width,
                        height: box.height * imageSize.height
                    )
                    
                    if let index = trackedTargets.firstIndex(where: { $0.id == id }) {
                        trackedTargets[index].boundingBox = rect
                        trackedTargets[index].trackingConfidence = observation.confidence
                        trackedTargets[index].lastUpdated = Date()
                        trackedTargets[index].framesSinceLastUpdate = 0
                    }
                    
                    lastObservations[id] = observation
                    
                    // 更新请求的输入观察
                    request.inputObservation = observation
                }
            } catch {
                print("追踪更新失败: \(error)")
            }
        }
    }
    
    private func findMatchingTarget(for detection: SuspectRegion) -> TrackedTarget? {
        for target in trackedTargets {
            let iou = calculateIOU(detection.boundingBox, target.boundingBox)
            if iou > iouThreshold {
                return target
            }
        }
        return nil
    }
    
    private func updateTarget(_ id: UUID, with detection: SuspectRegion) {
        if let index = trackedTargets.firstIndex(where: { $0.id == id }) {
            // 平滑更新位置（避免抖动）
            let smoothFactor: CGFloat = 0.3
            let currentBox = trackedTargets[index].boundingBox
            let newBox = CGRect(
                x: currentBox.origin.x * (1 - smoothFactor) + detection.boundingBox.origin.x * smoothFactor,
                y: currentBox.origin.y * (1 - smoothFactor) + detection.boundingBox.origin.y * smoothFactor,
                width: currentBox.width * (1 - smoothFactor) + detection.boundingBox.width * smoothFactor,
                height: currentBox.height * (1 - smoothFactor) + detection.boundingBox.height * smoothFactor
            )
            
            trackedTargets[index].boundingBox = newBox
            trackedTargets[index].trackingConfidence = max(
                trackedTargets[index].trackingConfidence * 0.6,
                detection.confidence
            )
            trackedTargets[index].lastUpdated = Date()
            trackedTargets[index].framesSinceLastUpdate = 0
            trackedTargets[index].detectedFrameCount += 1 // 持续检测计数
            trackedTargets[index].framesMissed = 0        // 重置丢失计数
            trackedTargets[index].visibility = 1.0        // 恢复不透明
        }
    }
    
    private func markMissedTargets(matchedTargetIDs: Set<UUID>) {
        // 对于在本帧没有匹配到雷达探测的目标
        for index in trackedTargets.indices {
            let id = trackedTargets[index].id
            
            if !matchedTargetIDs.contains(id) {
                // 仅对未匹配的目标增加丢失计数
                trackedTargets[index].framesMissed += 1
            }
        }
    }
    
    private func addNewTarget(from detection: SuspectRegion, in pixelBuffer: CVPixelBuffer, imageSize: CGSize) {
        let newTarget = TrackedTarget(
            boundingBox: detection.boundingBox,
            trackingConfidence: detection.confidence,
            state: .suspect,
            detectedFrameCount: 1,
            requiredStableFrames: requiredStableFrames
        )
        
        trackedTargets.append(newTarget)
        
        // 创建 Vision 追踪请求
        if useVisionTracking {
            // 转换为归一化坐标
            let normalizedBox = CGRect(
                x: detection.boundingBox.origin.x / imageSize.width,
                y: 1 - (detection.boundingBox.origin.y + detection.boundingBox.height) / imageSize.height,
                width: detection.boundingBox.width / imageSize.width,
                height: detection.boundingBox.height / imageSize.height
            )
            
            let observation = VNDetectedObjectObservation(boundingBox: normalizedBox)
            let request = VNTrackObjectRequest(detectedObjectObservation: observation)
            request.trackingLevel = .fast
            
            trackingRequests[newTarget.id] = request
            lastObservations[newTarget.id] = observation
        }
    }
    
    private func cleanupStaleTargets() {
        // 1. 增加帧计数并处理透明度渐变 (Phase 2.8 记忆期)
        for index in trackedTargets.indices {
            trackedTargets[index].framesSinceLastUpdate += 1
            
            // 如果连续丢失帧数 > 1，开始虚化
            if trackedTargets[index].framesMissed > 1 {
                // 5 帧记忆期 (10FPS 下约 0.5s)
                let lifeProgress = Double(trackedTargets[index].framesMissed) / 5.0
                trackedTargets[index].visibility = max(0.0, 1.0 - lifeProgress)
            }
        }
        
        // 2. 移除彻底消失的目标
        // 移除条件：超出生命周期 或 丢失帧数过多
        let staleIDs = trackedTargets
            .filter { $0.framesSinceLastUpdate > maxLifetimeFrames || $0.framesMissed > 5 }
            .map { $0.id }
        
        for id in staleIDs {
            removeTarget(id)
        }
    }
    
    /// 计算两个矩形的 IOU (Intersection over Union)
    private func calculateIOU(_ rect1: CGRect, _ rect2: CGRect) -> Float {
        let intersection = rect1.intersection(rect2)
        
        if intersection.isNull || intersection.isEmpty {
            return 0
        }
        
        let intersectionArea = intersection.width * intersection.height
        let unionArea = rect1.width * rect1.height + rect2.width * rect2.height - intersectionArea
        
        return Float(intersectionArea / unionArea)
    }
}
