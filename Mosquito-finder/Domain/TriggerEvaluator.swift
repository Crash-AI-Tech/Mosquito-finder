//
//  TriggerEvaluator.swift
//  Mosquito-finder
//
//  触发评估器 - 判断是否满足 Stage 2 触发条件
//

import Foundation
import CoreGraphics

/// 触发评估器
struct TriggerEvaluator {
    
    // MARK: - Configuration
    
    /// 触发 Stage 2 的最小变焦倍数（1.5x：需要主动拉近，防止无意触发）
    var minZoomFactor: CGFloat = 1.5
    
    /// 中心区域半径（相对于屏幕短边的比例）
    var centerRegionRatio: CGFloat = 0.20
    
    /// 触发 Stage 2 的最小目标尺寸（像素）
    var minTargetSize: CGFloat = 15
    
    // MARK: - Public Methods
    
    /// 评估是否应该激活 Stage 2
    func shouldActivateStage2(
        target: TrackedTarget,
        zoomFactor: CGFloat,
        isApproaching: Bool,
        screenSize: CGSize
    ) -> Bool {
        // 条件 1: 目标在屏幕中心区域
        let isInCenter = isTargetInCenter(target: target, screenSize: screenSize)
        
        // 条件 2: 变焦足够大（minZoomFactor=1.5，需要手动拉近）
        let isZoomedIn = zoomFactor >= minZoomFactor
        
        // 条件 4: 目标尺寸足够大（Stage1 框约 22px，阈值 15px）
        let isBigEnough = target.size.width >= minTargetSize || target.size.height >= minTargetSize
        
        // 必须变焦 AND 在中心区域才触发 Stage 2
        // 去掉 isApproaching 作为独立触发条件：手机移动时 isApproaching=true 会大量误报
        let triggerConditionMet = isInCenter && isZoomedIn
        
        return triggerConditionMet && isBigEnough
    }
    
    /// 检查目标是否在屏幕中心
    func isTargetInCenter(target: TrackedTarget, screenSize: CGSize) -> Bool {
        let screenCenter = CGPoint(x: screenSize.width / 2, y: screenSize.height / 2)
        let centerRadius = min(screenSize.width, screenSize.height) * centerRegionRatio
        
        let distance = hypot(target.center.x - screenCenter.x, target.center.y - screenCenter.y)
        
        return distance <= centerRadius
    }
    
    /// 计算目标到中心的距离
    func distanceToCenter(target: TrackedTarget, screenSize: CGSize) -> CGFloat {
        let screenCenter = CGPoint(x: screenSize.width / 2, y: screenSize.height / 2)
        return hypot(target.center.x - screenCenter.x, target.center.y - screenCenter.y)
    }
    
    /// 获取满足的触发条件列表
    func getActiveTriggers(
        target: TrackedTarget,
        zoomFactor: CGFloat,
        isApproaching: Bool,
        screenSize: CGSize
    ) -> [String] {
        var triggers: [String] = []
        
        if isTargetInCenter(target: target, screenSize: screenSize) {
            triggers.append("center")
        }
        
        if zoomFactor >= minZoomFactor {
            triggers.append("zoom")
        }
        
        if isApproaching {
            triggers.append("approaching")
        }
        
        if target.size.width >= minTargetSize && target.size.height >= minTargetSize {
            triggers.append("size")
        }
        
        return triggers
    }
}
