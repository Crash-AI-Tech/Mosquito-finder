//
//  FlashlightManager.swift
//  Mosquito-finder
//
//  手电筒管理器
//

import AVFoundation
import Combine

/// 手电筒管理器
class FlashlightManager: ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var isOn = false
    @Published var brightness: Float = 1.0  // 0.0 - 1.0
    
    // MARK: - Private Properties
    
    private var device: AVCaptureDevice?
    private let queue = DispatchQueue(label: "com.mosquitofinder.flashlight")
    
    // MARK: - Init
    
    init() {
        device = AVCaptureDevice.default(for: .video)
    }
    
    // MARK: - Public Methods
    
    /// 更新设备引用（解决多摄切换后的引用问题）
    func updateDevice(_ newDevice: AVCaptureDevice?) {
        self.device = newDevice
    }
    
    /// 打开手电筒
    func turnOn(brightness: Float = 1.0) {
        queue.async { [weak self] in
            guard let self = self, let device = self.device, device.hasTorch else { return }
            
            do {
                try device.lockForConfiguration()
                
                if brightness < 1.0 {
                    try device.setTorchModeOn(level: max(0.01, min(brightness, 1.0)))
                } else {
                    device.torchMode = .on
                }
                
                device.unlockForConfiguration()
                
                DispatchQueue.main.async {
                    self.isOn = true
                    self.brightness = brightness
                }
            } catch {
                print("手电筒打开失败: \(error)")
            }
        }
    }
    
    /// 关闭手电筒
    func turnOff() {
        queue.async { [weak self] in
            guard let self = self, let device = self.device, device.hasTorch else { return }
            
            do {
                try device.lockForConfiguration()
                device.torchMode = .off
                device.unlockForConfiguration()
                
                DispatchQueue.main.async {
                    self.isOn = false
                }
            } catch {
                print("手电筒关闭失败: \(error)")
            }
        }
    }
    
    /// 切换手电筒状态
    func toggle() {
        if isOn {
            turnOff()
        } else {
            turnOn(brightness: brightness)
        }
    }
    
    /// 调整亮度
    func setBrightness(_ level: Float) {
        brightness = max(0.0, min(level, 1.0))
        if isOn {
            turnOn(brightness: brightness)
        }
    }
}
