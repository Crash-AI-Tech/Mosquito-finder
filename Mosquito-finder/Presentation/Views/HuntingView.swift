
import SwiftUI
import AVFoundation

/// 主狩猎界面
struct HuntingView: View {
    @StateObject private var viewModel = HuntingViewModel()

    var body: some View {
        ZStack {
            // 1. 强制底色为黑色，防止出现白色空白
            Color.black.ignoresSafeArea()
            
            // 2. 诊断层 - 确认 View 已加载
            VStack {
                Text("SYSTEM READY")
                    .font(.system(.caption, design: .monospaced))
                    .foregroundColor(.green.opacity(0.3))
                Spacer()
            }
            .padding(.top, 50)
            
            // 3. 背景 - 相机预览
            CameraPreviewView(session: viewModel.cameraController.captureSession)
                .ignoresSafeArea()
            
            // 4. 夜视仪滤镜效果
            nightVisionOverlay
                .opacity(viewModel.isSessionActive ? 1.0 : 0.0)
            
            // 5. SwiftUI 目标覆盖层
            TargetOverlayView(
                targets: viewModel.trackedTargets,
                activeTarget: viewModel.activeTarget,
                classificationResult: viewModel.classificationResult,
                imageSize: viewModel.nativeImageSize
            )
            .ignoresSafeArea()
            .opacity(viewModel.isSessionActive ? 1.0 : 0.0)
            
            // 6. HUD 控制层
            VStack {
                // 顶部状态栏
                topStatusBar
                
                Spacer()
                
                // 中心准星
                crosshair
                
                Spacer()
                
                // 底部控制栏
                bottomControlBar
            }
            .padding()
            .opacity(viewModel.isSessionActive ? 1.0 : 0.0)
            
            // 7. 启动覆盖层
            if !viewModel.isSessionActive {
                startOverlay
            }
            
            // 6. 发现蚊子提示
            if viewModel.currentPhase == .killing {
                mosquitoFoundAlert
            }
            
            // 7. 诊断文字（仅在出错时显示）
            if let error = viewModel.errorMessage {
                VStack {
                    Text("错误: \(error)")
                        .foregroundColor(.red)
                        .padding()
                        .background(Color.black.opacity(0.8))
                        .cornerRadius(10)
                    Spacer()
                }
                .padding(.top, 100)
            }
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
    }
    
    // MARK: - Night Vision Overlay
    
    private var nightVisionOverlay: some View {
        Color.green.opacity(0.05)
            .ignoresSafeArea()
            .allowsHitTesting(false)
    }
    
    // MARK: - Top Status Bar
    
    private var topStatusBar: some View {
        HStack {
            // 状态指示
            HStack(spacing: 8) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 10, height: 10)
                
                Text(viewModel.currentPhase.displayName)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundColor(.green)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color.black.opacity(0.6))
            .cornerRadius(8)
            
            Spacer()
            
            // 会话时间
            Text(viewModel.sessionDuration)
                .font(.system(.title3, design: .monospaced))
                .foregroundColor(.green)
            
            Spacer()
            
            // 发现计数
            HStack(spacing: 4) {
                Image(systemName: "target")
                Text("\(viewModel.mosquitoesFound)")
                    .font(.system(.caption, design: .monospaced))
            }
            .foregroundColor(.red)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color.black.opacity(0.6))
            .cornerRadius(8)
        }
    }
    
    // MARK: - Crosshair
    
    private var crosshair: some View {
        ZStack {
            // 外圈
            Circle()
                .stroke(Color.green.opacity(0.5), lineWidth: 1)
                .frame(width: 100, height: 100)
            
            // 十字线
            Rectangle()
                .fill(Color.green.opacity(0.8))
                .frame(width: 1, height: 80)
            
            Rectangle()
                .fill(Color.green.opacity(0.8))
                .frame(width: 80, height: 1)
            
            // 中心点
            Circle()
                .fill(Color.green)
                .frame(width: 6, height: 6)
            
            // 对焦锁定指示
            if viewModel.isFocusLocked {
                Circle()
                    .stroke(Color.red, lineWidth: 2)
                    .frame(width: 40, height: 40)
            }
        }
    }
    
    // MARK: - Bottom Control Bar
    
    private var bottomControlBar: some View {
        HStack(spacing: 30) {
            // 闪光灯按钮
            Button(action: { viewModel.toggleFlashlight() }) {
                VStack(spacing: 4) {
                    Image(systemName: viewModel.isFlashlightOn ? "flashlight.on.fill" : "flashlight.off.fill")
                        .font(.title2)
                    Text("灯光")
                        .font(.caption2)
                }
                .foregroundColor(viewModel.isFlashlightOn ? .yellow : .gray)
            }
            
            // 对焦锁定按钮
            Button(action: { viewModel.toggleFocusLock() }) {
                VStack(spacing: 4) {
                    Image(systemName: viewModel.isFocusLocked ? "lock.fill" : "lock.open.fill")
                        .font(.title2)
                    Text("对焦")
                        .font(.caption2)
                }
                .foregroundColor(viewModel.isFocusLocked ? .red : .gray)
            }
            
            // 停止按钮
            Button(action: { viewModel.stopHunting() }) {
                VStack(spacing: 4) {
                    Image(systemName: "stop.circle.fill")
                        .font(.title)
                    Text("停止")
                        .font(.caption2)
                }
                .foregroundColor(.red)
            }
            
            // 变焦滑块
            VStack(spacing: 4) {
                Slider(
                    value: Binding(
                        get: { viewModel.currentZoomFactor },
                        set: { viewModel.setZoom($0) }
                    ),
                    in: 1...10
                )
                .accentColor(.green)
                .frame(width: 100)
                
                Text("\(viewModel.currentZoomFactor, specifier: "%.1f")x")
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundColor(.green)
            }
        }
        .padding()
        .background(Color.black.opacity(0.6))
        .cornerRadius(12)
    }
    
    // MARK: - Start Overlay
    
    private var startOverlay: some View {
        ZStack {
            Color.black.opacity(0.9)
                .ignoresSafeArea()
            
            VStack(spacing: 30) {
                // Logo/标题
                VStack(spacing: 10) {
                    Image(systemName: "ant.circle.fill")
                        .font(.system(size: 80))
                        .foregroundColor(.green)
                    
                    Text("猎蚊者")
                        .font(.system(size: 36, weight: .bold, design: .rounded))
                        .foregroundColor(.white)
                    
                    Text("MOSQUITO FINDER")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.green)
                }
                
                // 说明文字
                VStack(spacing: 8) {
                    Text("🔦 自动开启闪光灯")
                    Text("📍 扫描墙面寻找可疑目标")
                    Text("🎯 靠近或变焦确认蚊子")
                }
                .font(.subheadline)
                .foregroundColor(.gray)
                
                // 开始按钮
                Button(action: { viewModel.startHunting() }) {
                    HStack {
                        Image(systemName: "play.fill")
                        Text("开始狩猎")
                    }
                    .font(.headline)
                    .foregroundColor(.black)
                    .padding(.horizontal, 40)
                    .padding(.vertical, 16)
                    .background(Color.green)
                    .cornerRadius(25)
                }
            }
        }
    }
    
    // MARK: - Mosquito Found Alert
    
    private var mosquitoFoundAlert: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 60))
                .foregroundColor(.red)
            
            Text("发现蚊子!")
                .font(.system(size: 28, weight: .bold))
                .foregroundColor(.white)
            
            if let result = viewModel.classificationResult {
                Text("置信度: \(result.confidencePercentage)")
                    .font(.system(.title3, design: .monospaced))
                    .foregroundColor(.green)
            }
            
            Button(action: {
                if let target = viewModel.activeTarget {
                    viewModel.dismissTarget(target)
                }
            }) {
                Text("已处理")
                    .font(.headline)
                    .foregroundColor(.black)
                    .padding(.horizontal, 30)
                    .padding(.vertical, 12)
                    .background(Color.green)
                    .cornerRadius(20)
            }
        }
        .padding(30)
        .background(Color.black.opacity(0.85))
        .cornerRadius(20)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .stroke(Color.red, lineWidth: 3)
        )
        .transition(.scale.combined(with: .opacity))
        .animation(.spring(), value: viewModel.currentPhase)
    }
    
    // MARK: - Helper
    
    private var statusColor: Color {
        switch viewModel.currentPhase {
        case .idle: return .gray
        case .scanning: return .green
        case .engaging: return .orange
        case .killing: return .red
        }
    }
}

// MARK: - Camera Preview View

/// 相机预览视图 - 使用 UIViewControllerRepresentable 确保正确布局
struct CameraPreviewView: UIViewControllerRepresentable {
    let session: AVCaptureSession
    
    func makeUIViewController(context: Context) -> CameraPreviewViewController {
        let controller = CameraPreviewViewController()
        controller.session = session
        return controller
    }
    
    func updateUIViewController(_ uiViewController: CameraPreviewViewController, context: Context) {
        // Session 已在 makeUIViewController 中设置
    }
}

/// 相机预览控制器
class CameraPreviewViewController: UIViewController {
    var session: AVCaptureSession?
    private var previewLayer: AVCaptureVideoPreviewLayer?
    
    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        
        guard let session = session else { return }
        
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        self.previewLayer = layer
    }
    
    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        // 关键：在布局变化时更新预览层尺寸
        previewLayer?.frame = view.bounds
    }
    
    override var prefersStatusBarHidden: Bool {
        return true
    }
}

#Preview {
    HuntingView()
}

