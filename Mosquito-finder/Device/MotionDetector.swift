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
    
    // MARK: - Private Properties
    
    private let motionManager = CMMotionManager()
    private var isRunning = false
    
    /// 检测阈值 - Z轴加速度小于此值视为"靠近"
    private let approachThreshold: Double = -0.3
    
    /// 平滑系数
    private let smoothingFactor: Double = 0.2
    
    /// 平滑后的加速度
    private var smoothedAcceleration: CMAcceleration = CMAcceleration(x: 0, y: 0, z: 0)
    
    // MARK: - Public Methods
    
    /// 开始监测
    func start() {
        guard motionManager.isAccelerometerAvailable, !isRunning else { return }
        
        motionManager.accelerometerUpdateInterval = 0.1  // 10Hz
        motionManager.startAccelerometerUpdates(to: .main) { [weak self] data, error in
            guard let self = self, let data = data else { return }
            
            // 低通滤波平滑
            self.smoothedAcceleration.x = self.smoothedAcceleration.x * (1 - self.smoothingFactor)
                + data.acceleration.x * self.smoothingFactor
            self.smoothedAcceleration.y = self.smoothedAcceleration.y * (1 - self.smoothingFactor)
                + data.acceleration.y * self.smoothingFactor
            self.smoothedAcceleration.z = self.smoothedAcceleration.z * (1 - self.smoothingFactor)
                + data.acceleration.z * self.smoothingFactor
            
            self.acceleration = self.smoothedAcceleration
            
            // 检测靠近动作（手机向前移动时 Z 轴负向加速）
            self.isApproaching = self.smoothedAcceleration.z < self.approachThreshold
        }
        
        isRunning = true
    }
    
    /// 停止监测
    func stop() {
        guard isRunning else { return }
        
        motionManager.stopAccelerometerUpdates()
        isRunning = false
        isApproaching = false
    }
    
    /// 检查是否支持运动检测
    var isAvailable: Bool {
        motionManager.isAccelerometerAvailable
    }
}
