//
//  HuntingStateManager.swift
//  Mosquito-finder
//
//  狩猎状态管理器 - 管理整个狩猎流程
//

import Foundation
import Combine
import CoreMotion

/// 狩猎状态管理器
class HuntingStateManager: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var currentPhase: HuntingPhase = .idle
    @Published var settings = DetectionSettings()
    @Published var activeTarget: TrackedTarget?
    @Published var lastClassificationResult: ClassificationResult?
    
    // MARK: - Statistics
    
    @Published var totalSuspectsFound: Int = 0
    @Published var mosquitoesConfirmed: Int = 0
    @Published var sessionStartTime: Date?
    
    // MARK: - Private Properties
    
    private var cancellables = Set<AnyCancellable>()
    
    // MARK: - Public Methods
    
    /// 开始狩猎会话
    func startSession() {
        currentPhase = .scanning
        sessionStartTime = Date()
        totalSuspectsFound = 0
        mosquitoesConfirmed = 0
        activeTarget = nil
        lastClassificationResult = nil
    }
    
    /// 结束狩猎会话
    func endSession() {
        currentPhase = .idle
        activeTarget = nil
    }
    
    /// 发现新的可疑目标
    func suspectDetected(count: Int) {
        if currentPhase == .scanning {
            totalSuspectsFound += count
        }
    }
    
    /// 开始锁定目标
    func engageTarget(_ target: TrackedTarget) {
        activeTarget = target
        currentPhase = .engaging
    }
    
    /// 确认目标分类结果
    func confirmClassification(_ result: ClassificationResult) {
        lastClassificationResult = result
        
        if result.isMosquito {
            currentPhase = .killing
            mosquitoesConfirmed += 1
        } else {
            // 不是蚊子，返回搜索模式
            currentPhase = .scanning
            activeTarget = nil
        }
    }
    
    /// 目标丢失或用户处理完毕
    func targetHandled() {
        currentPhase = .scanning
        activeTarget = nil
        lastClassificationResult = nil
    }
    
    /// 获取会话持续时间
    var sessionDuration: TimeInterval {
        guard let start = sessionStartTime else { return 0 }
        return Date().timeIntervalSince(start)
    }
    
    /// 格式化的会话时间
    var formattedDuration: String {
        let duration = Int(sessionDuration)
        let minutes = duration / 60
        let seconds = duration % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
