//
//  CameraController.swift
//  Mosquito-finder
//
//  相机控制器 - 管理 AVCaptureSession、镜头切换、对焦
//

import AVFoundation
import UIKit
import Combine

/// 相机控制器
class CameraController: NSObject, ObservableObject {
    
    // MARK: - Published Properties
    
    @Published var isRunning = false
    @Published var currentZoomFactor: CGFloat = 1.0
    @Published var isFocusLocked = false
    @Published var error: CameraError?
    
    // MARK: - Public Properties
    
    let captureSession = AVCaptureSession()
    var videoOutput: AVCaptureVideoDataOutput?
    
    /// 视频帧回调
    var onFrameCaptured: ((CMSampleBuffer) -> Void)?
    
    /// 最新一帧（用于截图）
    private(set) var latestPixelBuffer: CVPixelBuffer?
    
    // MARK: - Private Properties
    
    public private(set) var captureDevice: AVCaptureDevice?
    private let sessionQueue = DispatchQueue(label: "com.mosquitofinder.camera")
    private var isConfigured = false
    
    // MARK: - Camera Error
    
    enum CameraError: LocalizedError {
        case accessDenied
        case deviceNotFound
        case configurationFailed(String)
        
        var errorDescription: String? {
            switch self {
            case .accessDenied: return "相机访问被拒绝"
            case .deviceNotFound: return "未找到相机设备"
            case .configurationFailed(let msg): return "相机配置失败: \(msg)"
            }
        }
    }
    
    // MARK: - Public Methods
    
    /// 请求相机权限并配置
    func requestAccessAndConfigure() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            sessionQueue.async { self.configureSession() }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                if granted {
                    self?.sessionQueue.async { self?.configureSession() }
                } else {
                    DispatchQueue.main.async {
                        self?.error = .accessDenied
                    }
                }
            }
        default:
            DispatchQueue.main.async {
                self.error = .accessDenied
            }
        }
    }
    
    /// 启动相机
    func start() {
        sessionQueue.async {
            if !self.captureSession.isRunning {
                self.captureSession.startRunning()
                DispatchQueue.main.async {
                    self.isRunning = true
                }
            }
        }
    }
    
    /// 停止相机
    func stop() {
        sessionQueue.async {
            if self.captureSession.isRunning {
                self.captureSession.stopRunning()
                DispatchQueue.main.async {
                    self.isRunning = false
                }
            }
        }
    }
    
    /// 设置变焦倍数
    func setZoom(_ factor: CGFloat) {
        guard let device = captureDevice else { return }
        
        let clampedFactor = max(1.0, min(factor, device.maxAvailableVideoZoomFactor))
        
        do {
            try device.lockForConfiguration()
            device.videoZoomFactor = clampedFactor
            device.unlockForConfiguration()
            
            DispatchQueue.main.async {
                self.currentZoomFactor = clampedFactor
            }
        } catch {
            print("变焦设置失败: \(error)")
        }
    }
    
    /// 锁定对焦到屏幕中心
    func lockFocusOnCenter() {
        guard let device = captureDevice else { return }
        
        do {
            try device.lockForConfiguration()
            
            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
            }
            
            if device.isFocusModeSupported(.locked) {
                device.focusMode = .locked
            }
            
            device.unlockForConfiguration()
            
            DispatchQueue.main.async {
                self.isFocusLocked = true
            }
        } catch {
            print("对焦锁定失败: \(error)")
        }
    }
    
    /// 解锁对焦（恢复自动对焦）
    func unlockFocus() {        guard let device = captureDevice else { return }
        
        do {
            try device.lockForConfiguration()
            
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            
            device.unlockForConfiguration()
            
            DispatchQueue.main.async {
                self.isFocusLocked = false
            }
        } catch {
            print("对焦解锁失败: \(error)")
        }
    }

    /// 抓取当前帧快照（用于冻结画面）
    /// 自动根据 buffer 尺寸选择方向：横屏 buffer → .right（显示为竖屏），竖屏 → .up
    func captureSnapshot() -> UIImage? {
        guard let pixelBuffer = latestPixelBuffer else { return nil }
        let w = CVPixelBufferGetWidth(pixelBuffer)
        let h = CVPixelBufferGetHeight(pixelBuffer)
        // 横屏 buffer (w > h)：orientation .right 让 UIImage 以竖屏方向显示
        let orientation: UIImage.Orientation = w > h ? .right : .up
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let context = CIContext(options: [.useSoftwareRenderer: false])
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return nil }
        return UIImage(cgImage: cgImage, scale: 1.0, orientation: orientation)
    }
    
    // MARK: - Private Methods
    
    private func configureSession() {
        guard !isConfigured else { return }
        
        captureSession.beginConfiguration()
        captureSession.sessionPreset = .hd1920x1080
        
        // 1. 发现最佳摄像头设备 (优先三摄 > 双摄 > 广角)
        let deviceTypes: [AVCaptureDevice.DeviceType] = [
            .builtInTripleCamera,
            .builtInDualWideCamera,
            .builtInDualCamera,
            .builtInWideAngleCamera
        ]
        
        let discoverySession = AVCaptureDevice.DiscoverySession(
            deviceTypes: deviceTypes,
            mediaType: .video,
            position: .back
        )
        
        guard let device = discoverySession.devices.first else {
            DispatchQueue.main.async {
                self.error = .deviceNotFound
            }
            captureSession.commitConfiguration()
            return
        }
        
        self.captureDevice = device
        
        do {
            let input = try AVCaptureDeviceInput(device: device)
            if captureSession.canAddInput(input) {
                captureSession.addInput(input)
            }
            
            // 如果支持多镜头，开启自动切换
            if device.deviceType == .builtInTripleCamera || device.deviceType == .builtInDualWideCamera {
                // 默认将缩放系数设为 1.0 (广角主摄)
                // 提示：0.5 是超广角，但在雷达模式下 1.0 开始更符合直觉
                device.videoZoomFactor = 1.0
            }
            
        } catch {
            DispatchQueue.main.async {
                self.error = .configurationFailed(error.localizedDescription)
            }
            captureSession.commitConfiguration()
            return
        }
        
        // 2. 添加视频输出
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        output.setSampleBufferDelegate(self, queue: sessionQueue)
        
        if captureSession.canAddOutput(output) {
            captureSession.addOutput(output)
            self.videoOutput = output
            
            // 设置视频方向
            if let connection = output.connection(with: .video) {
                if connection.isVideoRotationAngleSupported(90) {
                    connection.videoRotationAngle = 90
                }
            }
        }
        
        captureSession.commitConfiguration()
        isConfigured = true
    }
}

// MARK: - AVCaptureVideoDataOutputSampleBufferDelegate

extension CameraController: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        // 保存最新帧供截图使用
        if let pb = CMSampleBufferGetImageBuffer(sampleBuffer) {
            latestPixelBuffer = pb
        }
        onFrameCaptured?(sampleBuffer)
    }
}
