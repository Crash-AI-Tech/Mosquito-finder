//
//  HapticsEngine.swift
//  Mosquito-finder
//
//  触觉反馈引擎
//

import Foundation
import Combine
import UIKit
import CoreHaptics

/// 触觉反馈引擎
class HapticsEngine: ObservableObject {
    
    // MARK: - Properties
    
    @Published var isEnabled = true
    
    private var hapticEngine: CHHapticEngine?
    private let impactLight = UIImpactFeedbackGenerator(style: .light)
    private let impactMedium = UIImpactFeedbackGenerator(style: .medium)
    private let impactHeavy = UIImpactFeedbackGenerator(style: .heavy)
    private let notification = UINotificationFeedbackGenerator()
    
    // MARK: - Init
    
    init() {
        prepareHaptics()
    }
    
    // MARK: - Public Methods
    
    /// 发现可疑目标 - 轻微震动
    func suspectDetected() {
        guard isEnabled else { return }
        impactLight.impactOccurred()
    }
    
    /// 目标锁定中 - 中等震动
    func targetEngaging() {
        guard isEnabled else { return }
        impactMedium.impactOccurred()
    }
    
    /// 确认是蚊子 - 强烈震动 + 成功反馈
    func mosquitoConfirmed() {
        guard isEnabled else { return }
        
        // 先震动
        impactHeavy.impactOccurred()
        
        // 延迟后再给个成功反馈
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            self.notification.notificationOccurred(.success)
        }
        
        // 自定义连续震动模式
        playConfirmationPattern()
    }
    
    /// 确认不是蚊子 - 轻微失败反馈
    func targetDismissed() {
        guard isEnabled else { return }
        notification.notificationOccurred(.warning)
    }
    
    // MARK: - Private Methods
    
    private func prepareHaptics() {
        impactLight.prepare()
        impactMedium.prepare()
        impactHeavy.prepare()
        notification.prepare()
        
        // 初始化 CoreHaptics 引擎
        guard CHHapticEngine.capabilitiesForHardware().supportsHaptics else { return }
        
        do {
            hapticEngine = try CHHapticEngine()
            try hapticEngine?.start()
            
            // 引擎停止时自动重启
            hapticEngine?.stoppedHandler = { [weak self] reason in
                print("触觉引擎停止: \(reason)")
                do {
                    try self?.hapticEngine?.start()
                } catch {
                    print("触觉引擎重启失败: \(error)")
                }
            }
        } catch {
            print("触觉引擎初始化失败: \(error)")
        }
    }
    
    /// 播放确认震动模式 (三连击)
    private func playConfirmationPattern() {
        guard let engine = hapticEngine else { return }
        
        do {
            // 创建三连击模式
            let events: [CHHapticEvent] = [
                CHHapticEvent(
                    eventType: .hapticTransient,
                    parameters: [
                        CHHapticEventParameter(parameterID: .hapticIntensity, value: 1.0),
                        CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.5)
                    ],
                    relativeTime: 0
                ),
                CHHapticEvent(
                    eventType: .hapticTransient,
                    parameters: [
                        CHHapticEventParameter(parameterID: .hapticIntensity, value: 0.8),
                        CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.5)
                    ],
                    relativeTime: 0.1
                ),
                CHHapticEvent(
                    eventType: .hapticTransient,
                    parameters: [
                        CHHapticEventParameter(parameterID: .hapticIntensity, value: 0.6),
                        CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.5)
                    ],
                    relativeTime: 0.2
                )
            ]
            
            let pattern = try CHHapticPattern(events: events, parameters: [])
            let player = try engine.makePlayer(with: pattern)
            try player.start(atTime: 0)
        } catch {
            print("触觉模式播放失败: \(error)")
        }
    }
}
