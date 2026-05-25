
import SwiftUI
import AVFoundation

// MARK: - Main View

struct HuntingView: View {
    @StateObject private var viewModel = HuntingViewModel()
    @AppStorage("appLanguage") private var appLanguage: String = ""

    private var currentLocale: Locale {
        switch appLanguage {
        case "en":      return Locale(identifier: "en_US")
        case "zh-Hans": return Locale(identifier: "zh-Hans")
        default:
            let code = Locale.current.language.languageCode?.identifier ?? "en"
            return code.hasPrefix("zh") ? Locale(identifier: "zh-Hans") : Locale(identifier: "en_US")
        }
    }

    private var isChineseActive: Bool {
        switch appLanguage {
        case "en":      return false
        case "zh-Hans": return true
        default:
            let code = Locale.current.language.languageCode?.identifier ?? "en"
            return code.hasPrefix("zh")
        }
    }

    private func toggleLanguage() {
        appLanguage = isChineseActive ? "en" : "zh-Hans"
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color.black.ignoresSafeArea()

                // 相机画面（发现蚊子时被冻结帧覆盖）
                CameraPreviewView(session: viewModel.cameraController.captureSession)
                    .ignoresSafeArea()

                // 夜视仪绿色薄膜 + 扫描线（仅扫描阶段）
                if viewModel.isSessionActive && viewModel.currentPhase != .killing {
                    Color.green.opacity(0.04)
                        .ignoresSafeArea()
                        .allowsHitTesting(false)

                    ScanLineView()
                        .ignoresSafeArea()
                }

                // 冻结帧（发现蚊子后定格画面）
                if viewModel.currentPhase == .killing, let frozen = viewModel.frozenFrame {
                    GeometryReader { geo in
                        Image(uiImage: frozen)
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: geo.size.width, height: geo.size.height)
                            .clipped()
                    }
                    .ignoresSafeArea()
                }

                // 目标覆盖层（非发现阶段）
                if viewModel.currentPhase != .killing {
                    TargetOverlayView(
                        targets: viewModel.trackedTargets,
                        activeTarget: viewModel.activeTarget,
                        classificationResult: viewModel.classificationResult,
                        imageSize: viewModel.nativeImageSize
                    )
                    .ignoresSafeArea()
                    .opacity(viewModel.isSessionActive ? 1 : 0)
                }

                // 发现阶段红框标注
                if viewModel.currentPhase == .killing {
                    frozenTargetHighlight
                }

                // 准星（仅扫描/锁定阶段）
                if viewModel.isSessionActive && viewModel.currentPhase != .killing {
                    TacticalCrosshair(
                        isLocked: viewModel.isFocusLocked,
                        hasTarget: viewModel.activeTarget != nil
                    )
                }

                // 主 HUD
                if viewModel.isSessionActive {
                    VStack(spacing: 0) {
                        topStatusBar
                            .padding(.horizontal, 16)
                            .padding(.top, 12)

                        Spacer()

                        // 发现阶段隐藏控制栏，改为紧凑面板
                        if viewModel.currentPhase != .killing {
                            bottomControlBar
                                .padding(.horizontal, 16)
                                .padding(.bottom, 32)
                        }
                    }
                }

                // 启动页
                if !viewModel.isSessionActive {
                    startOverlay
                }

                // 发现蚊子：紧凑底部面板
                if viewModel.currentPhase == .killing {
                    mosquitoFoundPanel
                }

                // 错误提示
                if let error = viewModel.errorMessage {
                    VStack {
                        Text("Error: \(error)")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundColor(.red)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(Color.black.opacity(0.75))
                            .cornerRadius(8)
                        Spacer()
                    }
                    .padding(.top, 80)
                }
            }
            .onAppear { viewModel.updatePreviewSize(geometry.size) }
            .onChange(of: geometry.size) { _, s in viewModel.updatePreviewSize(s) }
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .environment(\.locale, currentLocale)
    }

    // MARK: - Top Status Bar

    private var topStatusBar: some View {
        HStack(spacing: 0) {
            // 阶段徽章
            HStack(spacing: 6) {
                Circle()
                    .fill(phaseColor)
                    .frame(width: 7, height: 7)
                Text(viewModel.currentPhase.localizedKey)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .textCase(.uppercase)
                    .foregroundColor(phaseColor)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.black.opacity(0.55))
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(phaseColor.opacity(0.4), lineWidth: 1)
            )
            .cornerRadius(6)

            Spacer()

            // 发现计数
            HStack(spacing: 5) {
                Image(systemName: "scope")
                    .font(.system(size: 11))
                Text("×\(viewModel.mosquitoesFound)")
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
            }
            .foregroundColor(viewModel.mosquitoesFound > 0 ? .red : Color(white: 0.5))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.black.opacity(0.55))
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke((viewModel.mosquitoesFound > 0 ? Color.red : Color(white: 0.3)).opacity(0.5), lineWidth: 1)
            )
            .cornerRadius(6)

            Spacer()

            // 计时器（细小次要）
            Text(viewModel.sessionDuration)
                .font(.system(size: 11, weight: .regular, design: .monospaced))
                .foregroundColor(Color.green.opacity(0.6))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.black.opacity(0.55))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.green.opacity(0.2), lineWidth: 1)
                )
                .cornerRadius(6)
        }
    }

    // MARK: - Diagnostics Panel (DEBUG only)

    private var diagnosticsPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("· VISION LINK ·")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundColor(.green.opacity(0.7))
            HStack(spacing: 14) {
                dMetric("S1", viewModel.diagnostics.stage1TimingText)
                dMetric("S2", viewModel.diagnostics.stage2TimingText)
                dMetric("CAND", "\(viewModel.diagnostics.stage1CandidateCount)")
                dMetric("TRK", "\(viewModel.diagnostics.stableTargetCount)")
                dMetric("ZOOM", String(format: "%.1fx", viewModel.diagnostics.currentZoomFactor))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(8)
        .background(Color.black.opacity(0.5))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.green.opacity(0.15), lineWidth: 1))
        .cornerRadius(8)
    }

    private func dMetric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title)
                .font(.system(size: 8, design: .monospaced))
                .foregroundColor(.gray)
            Text(value)
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundColor(.green)
                .lineLimit(1)
        }
    }

    // MARK: - Bottom Control Bar

    private var bottomControlBar: some View {
        VStack(spacing: 14) {
            // 变焦条
            HStack(spacing: 10) {
                Image(systemName: "minus.magnifyingglass")
                    .font(.system(size: 13))
                    .foregroundColor(.green.opacity(0.6))
                Slider(
                    value: Binding(
                        get: { viewModel.currentZoomFactor },
                        set: { viewModel.setZoom($0) }
                    ),
                    in: 1...10
                )
                .tint(.green)
                Image(systemName: "plus.magnifyingglass")
                    .font(.system(size: 13))
                    .foregroundColor(.green.opacity(0.6))
                Text(String(format: "%.1f×", viewModel.currentZoomFactor))
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundColor(.green)
                    .frame(width: 40)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(Color.white.opacity(0.12), lineWidth: 0.5)
            )

            // 三个操作按钮
            HStack(spacing: 0) {
                // 闪光灯
                controlButton(
                    icon: viewModel.isFlashlightOn ? "flashlight.on.fill" : "flashlight.off.fill",
                    label: "Light",
                    color: viewModel.isFlashlightOn ? .yellow : Color(white: 0.45),
                    action: { viewModel.toggleFlashlight() }
                )

                Divider()
                    .frame(width: 1, height: 40)
                    .background(Color.white.opacity(0.1))

                // 对焦锁
                controlButton(
                    icon: viewModel.isFocusLocked ? "lock.fill" : "lock.open.fill",
                    label: "Focus",
                    color: viewModel.isFocusLocked ? .red : Color(white: 0.45),
                    action: { viewModel.toggleFocusLock() }
                )

                Divider()
                    .frame(width: 1, height: 40)
                    .background(Color.white.opacity(0.1))

                // 结束
                controlButton(
                    icon: "stop.circle.fill",
                    label: "End",
                    color: .red,
                    action: { viewModel.stopHunting() }
                )
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 32, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 32, style: .continuous)
                    .stroke(Color.white.opacity(0.14), lineWidth: 0.5)
            )
        }
    }

    private func controlButton(icon: String, label: LocalizedStringKey, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 22))
                Text(label)
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
            }
            .foregroundColor(color)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }
    }

    // MARK: - Start Overlay

    private var startOverlay: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            RadarPulseView()
                .frame(width: 320, height: 320)
                .opacity(0.4)

            VStack(spacing: 0) {
                // 顶部语言切换按钮
                HStack {
                    Button(action: toggleLanguage) {
                        Text(isChineseActive ? "EN" : "中")
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .foregroundColor(.green.opacity(0.8))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6, style: .continuous)
                                    .stroke(Color.green.opacity(0.4), lineWidth: 1)
                            )
                    }
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.top, 20)

                Spacer()

                // App 名
                VStack(spacing: 8) {
                    Text("Mosquito Finder")
                        .font(.system(size: 38, weight: .bold, design: .default))
                        .foregroundColor(.white)
                        .tracking(1)
                    Text("THREAT DETECTION SYSTEM")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundColor(.green.opacity(0.7))
                        .tracking(3)
                }

                Spacer().frame(height: 48)

                // 功能说明三行
                VStack(spacing: 14) {
                    featureRow(icon: "flashlight.on.fill",  color: .yellow, text: "🔦 Flashlight, focus lock & zoom")
                    featureRow(icon: "viewfinder",           color: .green,  text: "📍 Scan walls for suspicious targets")
                    featureRow(icon: "scope",               color: .orange, text: "🎯 Zoom in to confirm mosquito")
                }
                .padding(.horizontal, 36)

                Spacer().frame(height: 52)

                // 开始按钮
                Button(action: { viewModel.startHunting() }) {
                    HStack(spacing: 10) {
                        Image(systemName: "play.fill")
                            .font(.system(size: 14, weight: .bold))
                        Text("Start Hunting")
                            .font(.system(size: 17, weight: .bold, design: .default))
                    }
                    .foregroundColor(.black)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 18)
                    .background(
                        LinearGradient(
                            colors: [Color(red: 0.2, green: 0.95, blue: 0.4),
                                     Color(red: 0.1, green: 0.75, blue: 0.3)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .cornerRadius(16)
                    .shadow(color: .green.opacity(0.4), radius: 12, x: 0, y: 4)
                }
                .padding(.horizontal, 32)

                Spacer().frame(height: 56)

                Text("v1.0  ·  AI POWERED")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(Color(white: 0.3))
                    .padding(.bottom, 20)
            }
        }
    }

    private func featureRow(icon: String, color: Color, text: LocalizedStringKey) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundColor(color)
                .frame(width: 24)
            Text(text)
                .font(.system(size: 15))
                .foregroundColor(Color(white: 0.75))
            Spacer()
        }
    }

    // MARK: - Frozen Target Highlight（冻结帧上的红框）

    private var frozenTargetHighlight: some View {
        GeometryReader { geometry in
            let screenSize = geometry.size
            let bufferSize = viewModel.nativeImageSize   // buffer 真实尺寸
            let isLandscape = bufferSize.width > bufferSize.height
            // 显示尺寸始终视为竖屏
            let displaySize = isLandscape
                ? CGSize(width: bufferSize.height, height: bufferSize.width)
                : bufferSize

            let scaleW = screenSize.width / displaySize.width
            let scaleH = screenSize.height / displaySize.height
            let scale  = max(scaleW, scaleH)
            let offsetX = (displaySize.width * scale - screenSize.width) / 2
            let offsetY = (displaySize.height * scale - screenSize.height) / 2

            if let box = viewModel.frozenTargetRect {
                // 横屏 buffer 坐标旋转到竖屏显示坐标（90° CCW）
                let displayBox: CGRect = isLandscape
                    ? CGRect(
                        x: box.origin.y,
                        y: bufferSize.width - box.origin.x - box.width,
                        width: box.height,
                        height: box.width
                      )
                    : box

                let sx = displayBox.origin.x * scale - offsetX
                let sy = displayBox.origin.y * scale - offsetY
                let sw = max(displayBox.width  * scale, 44)
                let sh = max(displayBox.height * scale, 44)
                let cx = sx + sw / 2
                let cy = sy + sh / 2

                ZStack {
                    // 红色脱出外框
                    Rectangle()
                        .stroke(Color.red.opacity(0.5), lineWidth: 1)
                        .frame(width: sw + 24, height: sh + 24)
                        .position(x: cx, y: cy)

                    // 主红框
                    Rectangle()
                        .stroke(Color.red, lineWidth: 2)
                        .frame(width: sw, height: sh)
                        .position(x: cx, y: cy)

                    // 四角标记（单 Path 避免 id 冲突）
                    let hs: CGFloat = 14
                    let lw: CGFloat = 2.5
                    Path { p in
                        p.move(to:    CGPoint(x: sx + hs, y: sy))
                        p.addLine(to: CGPoint(x: sx,      y: sy))
                        p.addLine(to: CGPoint(x: sx,      y: sy + hs))
                        p.move(to:    CGPoint(x: sx + sw - hs, y: sy))
                        p.addLine(to: CGPoint(x: sx + sw,      y: sy))
                        p.addLine(to: CGPoint(x: sx + sw,      y: sy + hs))
                        p.move(to:    CGPoint(x: sx,      y: sy + sh - hs))
                        p.addLine(to: CGPoint(x: sx,      y: sy + sh))
                        p.addLine(to: CGPoint(x: sx + hs, y: sy + sh))
                        p.move(to:    CGPoint(x: sx + sw - hs, y: sy + sh))
                        p.addLine(to: CGPoint(x: sx + sw,      y: sy + sh))
                        p.addLine(to: CGPoint(x: sx + sw,      y: sy + sh - hs))
                    }
                    .stroke(Color.red, style: StrokeStyle(lineWidth: lw, lineCap: .square))

                    // 标签（双语，修正错别字）
                    Text(isChineseActive ? "目标锁定" : "TARGET LOCKED")
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundColor(.red)
                        .tracking(1)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Color.black.opacity(0.65))
                        .position(x: cx, y: sy - 14)
                }
            }
        }
        .ignoresSafeArea()
    }

    // MARK: - Mosquito Found Panel（紧凑底部面板）

    private var mosquitoFoundPanel: some View {
        VStack {
            Spacer()

            VStack(spacing: 14) {
                // 标题行（双语）
                HStack(spacing: 10) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.red)
                        .font(.system(size: 16))
                    Text(isChineseActive ? "发现蚊子！" : "MOSQUITO FOUND")
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundColor(.red)
                        .tracking(2)
                    Spacer()
                    if let result = viewModel.classificationResult {
                        Text(result.confidencePercentage)
                            .font(.system(size: 13, weight: .semibold, design: .monospaced))
                            .foregroundColor(.green)
                    }
                }

                // 置信度进度条
                if let result = viewModel.classificationResult,
                   let pct = parseConfidence(result.confidencePercentage) {
                    GeometryReader { g in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 3)
                                .fill(Color.white.opacity(0.1))
                            RoundedRectangle(cornerRadius: 3)
                                .fill(LinearGradient(
                                    colors: [.orange, .red],
                                    startPoint: .leading, endPoint: .trailing))
                                .frame(width: g.size.width * CGFloat(pct))
                        }
                    }
                    .frame(height: 4)
                }

                // 已处理按钮
                Button(action: {
                    if let target = viewModel.activeTarget {
                        viewModel.dismissTarget(target)
                    } else {
                        viewModel.dismissCurrentMosquito()
                    }
                }) {
                    Text("Done")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.red.opacity(0.85))
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
            }
            .padding(20)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
            .padding(.horizontal, 16)
            .padding(.bottom, 40)
        }
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: viewModel.currentPhase)
    }

    // MARK: - Helpers

    private var phaseColor: Color {
        switch viewModel.currentPhase {
        case .idle:     return Color(white: 0.5)
        case .scanning: return .green
        case .engaging: return .orange
        case .killing:  return .red
        }
    }

    private func parseConfidence(_ text: String) -> Double? {
        let digits = text.filter { $0.isNumber || $0 == "." }
        guard let v = Double(digits) else { return nil }
        return v > 1 ? v / 100.0 : v
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

