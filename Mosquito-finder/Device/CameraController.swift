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

    enum CaptureProfile {
        case handheld
        case stationaryFlight
    }
    
    // MARK: - Published Properties
    
    @Published var isRunning = false
    @Published var currentZoomFactor: CGFloat = 1.0
    @Published var isFocusLocked = false
    @Published var isCaptureLocked = false
    @Published var activeFramesPerSecond: Double = 0
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
    private let captureProfile: CaptureProfile

    init(captureProfile: CaptureProfile = .handheld) {
        self.captureProfile = captureProfile
        super.init()
    }
    
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
    func requestAccessAndConfigure(completion: ((Bool) -> Void)? = nil) {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            sessionQueue.async {
                let success = self.configureSession()
                DispatchQueue.main.async {
                    completion?(success)
                }
            }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                if granted {
                    self?.sessionQueue.async {
                        let success = self?.configureSession() ?? false
                        DispatchQueue.main.async {
                            completion?(success)
                        }
                    }
                } else {
                    DispatchQueue.main.async {
                        self?.error = .accessDenied
                        completion?(false)
                    }
                }
            }
        default:
            DispatchQueue.main.async {
                self.error = .accessDenied
                completion?(false)
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

    /// 将自动对焦和曝光移动到候选区域中心。坐标为 0...1 的相机画面坐标。
    func focusAndExpose(at normalizedPoint: CGPoint) {
        guard let device = captureDevice else { return }

        let point = CGPoint(
            x: max(0.02, min(0.98, normalizedPoint.x)),
            y: max(0.02, min(0.98, normalizedPoint.y))
        )

        do {
            try device.lockForConfiguration()

            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = point
                if device.isFocusModeSupported(.continuousAutoFocus) {
                    device.focusMode = .continuousAutoFocus
                } else if device.isFocusModeSupported(.autoFocus) {
                    device.focusMode = .autoFocus
                }
            }

            if device.isExposurePointOfInterestSupported {
                device.exposurePointOfInterest = point
                if device.isExposureModeSupported(.continuousAutoExposure) {
                    device.exposureMode = .continuousAutoExposure
                } else if device.isExposureModeSupported(.autoExpose) {
                    device.exposureMode = .autoExpose
                }
            }

            device.unlockForConfiguration()
        } catch {
            print("候选区域对焦/曝光失败: \(error)")
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

    /// 固定监测校准完成后锁定会制造伪运动的相机自动参数。
    func lockStationaryCapture() {
        guard captureProfile == .stationaryFlight, let device = captureDevice else { return }

        sessionQueue.async {
            do {
                try device.lockForConfiguration()
                if device.isFocusModeSupported(.locked) {
                    device.focusMode = .locked
                }
                if device.isExposureModeSupported(.locked) {
                    device.exposureMode = .locked
                }
                if device.isWhiteBalanceModeSupported(.locked) {
                    device.whiteBalanceMode = .locked
                }
                device.unlockForConfiguration()

                DispatchQueue.main.async {
                    self.isFocusLocked = true
                    self.isCaptureLocked = true
                }
            } catch {
                print("固定监测参数锁定失败: \(error)")
            }
        }
    }

    /// 手机被移动后恢复自动参数，等待画面稳定后重新校准。
    func unlockStationaryCapture() {
        guard captureProfile == .stationaryFlight, let device = captureDevice else { return }

        sessionQueue.async {
            do {
                try device.lockForConfiguration()
                if device.isFocusModeSupported(.continuousAutoFocus) {
                    device.focusMode = .continuousAutoFocus
                }
                if device.isExposureModeSupported(.continuousAutoExposure) {
                    device.exposureMode = .continuousAutoExposure
                }
                if device.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                    device.whiteBalanceMode = .continuousAutoWhiteBalance
                }
                device.unlockForConfiguration()

                DispatchQueue.main.async {
                    self.isFocusLocked = false
                    self.isCaptureLocked = false
                }
            } catch {
                print("固定监测参数解锁失败: \(error)")
            }
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
    
    private func configureSession() -> Bool {
        guard !isConfigured else { return true }
        
        captureSession.beginConfiguration()
        captureSession.sessionPreset = captureProfile == .stationaryFlight ? .inputPriority : .hd1920x1080
        
        // 1. 发现最佳摄像头设备 (优先三摄 > 双摄 > 广角)
        let deviceTypes: [AVCaptureDevice.DeviceType] = captureProfile == .stationaryFlight
            ? [.builtInWideAngleCamera]
            : [.builtInTripleCamera, .builtInDualWideCamera, .builtInDualCamera, .builtInWideAngleCamera]
        
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
            return false
        }
        
        self.captureDevice = device

        if captureProfile == .stationaryFlight {
            configureStationaryFormat(for: device)
        }
        
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
            return false
        }
        
        // 2. 添加视频输出
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: captureProfile == .stationaryFlight
                ? kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
                : kCVPixelFormatType_32BGRA
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
                if captureProfile == .stationaryFlight,
                   connection.isVideoStabilizationSupported {
                    connection.preferredVideoStabilizationMode = .off
                }
            }
        }
        
        captureSession.commitConfiguration()
        isConfigured = true
        return true
    }

    private func configureStationaryFormat(for device: AVCaptureDevice) {
        let targetWidth: Int32 = 1920
        let targetHeight: Int32 = 1080
        let requestedFPS = 60.0

        let candidates = device.formats.compactMap { format -> (AVCaptureDevice.Format, Double, Int32, Int32)? in
            let dimensions = CMVideoFormatDescriptionGetDimensions(format.formatDescription)
            let maxFPS = format.videoSupportedFrameRateRanges.map(\.maxFrameRate).max() ?? 0
            guard dimensions.width >= targetWidth,
                  dimensions.height >= targetHeight,
                  maxFPS >= 30 else {
                return nil
            }
            return (format, maxFPS, dimensions.width, dimensions.height)
        }

        let selected = candidates.sorted { lhs, rhs in
            let lhsExact = lhs.2 == targetWidth && lhs.3 == targetHeight
            let rhsExact = rhs.2 == targetWidth && rhs.3 == targetHeight
            if lhsExact != rhsExact { return lhsExact }
            let lhsSupportsRequested = lhs.1 >= requestedFPS
            let rhsSupportsRequested = rhs.1 >= requestedFPS
            if lhsSupportsRequested != rhsSupportsRequested { return lhsSupportsRequested }
            return Int64(lhs.2) * Int64(lhs.3) < Int64(rhs.2) * Int64(rhs.3)
        }.first

        guard let selected else { return }

        do {
            try device.lockForConfiguration()
            device.activeFormat = selected.0
            let fps = min(requestedFPS, selected.1)
            let duration = CMTime(value: 1, timescale: CMTimeScale(fps.rounded()))
            device.activeVideoMinFrameDuration = duration
            device.activeVideoMaxFrameDuration = duration
            device.videoZoomFactor = 1.0
            if device.isFocusPointOfInterestSupported {
                device.focusPointOfInterest = CGPoint(x: 0.5, y: 0.5)
            }
            if device.isFocusModeSupported(.continuousAutoFocus) {
                device.focusMode = .continuousAutoFocus
            }
            if device.isExposureModeSupported(.continuousAutoExposure) {
                device.exposureMode = .continuousAutoExposure
            }
            if device.isWhiteBalanceModeSupported(.continuousAutoWhiteBalance) {
                device.whiteBalanceMode = .continuousAutoWhiteBalance
            }
            device.unlockForConfiguration()

            DispatchQueue.main.async {
                self.activeFramesPerSecond = fps
            }
        } catch {
            print("固定监测相机格式配置失败: \(error)")
        }
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
