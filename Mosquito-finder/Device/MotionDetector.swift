//
//  MotionDetector.swift
//  Mosquito-finder
//
//  运动检测器 - 检测用户靠近动作
//

import CoreMotion
import Combine

/// 运动检测器
class MotionDetector: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var isApproaching = false
    @Published var acceleration: CMAcceleration = CMAcceleration(x: 0, y: 0, z: 0)
    /// 是否在抖动（抖动时暂停扫描）
    @Published var isShaking = false
    
    // MARK: - Private Properties
    
    private let motionManager = CMMotionManager()
    private var isRunning = false
    
    /// 检测阈值 - Z轴加速度小于此值视为"靠近"
    private let approachThreshold: Double = -0.3
    /// 抖动检测阈值：平滑加速度差分超过此值则认为在抖
    private let shakeThreshold: Double = 0.12
    
    /// 平滑系数
    private let smoothingFactor: Double = 0.2
    
    /// 平滑后的加速度
    private var smoothedAcceleration: CMAcceleration = CMAcceleration(x: 0, y: 0, z: 0)
    /// 运动幅度的指数平滑值（用于抖动检测）
    private var smoothedJerk: Double = 0
    
    // MARK: - Public Methods
    
    /// 开始监测
    func start() {
        guard motionManager.isAccelerometerAvailable, !isRunning else { return }
        
        motionManager.accelerometerUpdateInterval = 0.1  // 10Hz
        motionManager.startAccelerometerUpdates(to: .main) { [weak self] data, error in
            guard let self = self, let data = data else { return }
            
            // 保存当前平滑値
            let prev = self.smoothedAcceleration
            
            // 低通滤波平滑
            self.smoothedAcceleration.x = prev.x * (1 - self.smoothingFactor) + data.acceleration.x * self.smoothingFactor
            self.smoothedAcceleration.y = prev.y * (1 - self.smoothingFactor) + data.acceleration.y * self.smoothingFactor
            self.smoothedAcceleration.z = prev.z * (1 - self.smoothingFactor) + data.acceleration.z * self.smoothingFactor
            
            self.acceleration = self.smoothedAcceleration
            
            // 检测靠近动作（手机向前移动时 Z 轴负向加速）
            self.isApproaching = self.smoothedAcceleration.z < self.approachThreshold
            
            // 拖动检测：计算平滑加速度的差分（高频分量 = 拖动）
            let dx = self.smoothedAcceleration.x - prev.x
            let dy = self.smoothedAcceleration.y - prev.y
            let dz = self.smoothedAcceleration.z - prev.z
            let jerk = sqrt(dx*dx + dy*dy + dz*dz)
            // 指数平滑拖动分量
            self.smoothedJerk = self.smoothedJerk * 0.7 + jerk * 0.3
            self.isShaking = self.smoothedJerk > self.shakeThreshold
        }
        
        isRunning = true
    }
    
    /// 停止监测
    func stop() {
        guard isRunning else { return }
        
        motionManager.stopAccelerometerUpdates()
        isRunning = false
        isApproaching = false
        isShaking = false
        smoothedJerk = 0
    }
    
    /// 检查是否支持运动检测
    var isAvailable: Bool {
        motionManager.isAccelerometerAvailable
    }
}
