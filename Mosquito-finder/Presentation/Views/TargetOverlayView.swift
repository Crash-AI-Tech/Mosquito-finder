//
//  TargetOverlayView.swift
//  Mosquito-finder
//
//  目标标记覆盖层 - 绘制边界框
//

import SwiftUI

/// 目标覆盖层视图
struct TargetOverlayView: View {
    let targets: [TrackedTarget]
    let activeTarget: TrackedTarget?
    let classificationResult: ClassificationResult?
    let imageSize: CGSize // 原始像素尺寸 (如 1920x1080 横屏 或 1080x1920 竖屏)
    
    var body: some View {
        GeometryReader { geometry in
            let screenSize = geometry.size
            
            // 如果 buffer 是横屏（w > h），需要将坐标旋转到竖屏显示空间
            let isLandscape = imageSize.width > imageSize.height
            // 显示尺寸始终是竖屏
            let displaySize = isLandscape
                ? CGSize(width: imageSize.height, height: imageSize.width)
                : imageSize
            
            // AspectFill 缩放
            let scaleW = screenSize.width / displaySize.width
            let scaleH = screenSize.height / displaySize.height
            let scale = max(scaleW, scaleH)
            let offsetX = (displaySize.width * scale - screenSize.width) / 2
            let offsetY = (displaySize.height * scale - screenSize.height) / 2
            
            ForEach(targets) { target in
                let pixelBox = target.boundingBox
                
                // 横屏 buffer：90° CCW 旋转到竖屏显示坐标
                // landscape(x,y,w,h) in W×H → portrait(y, W-x-w, h, w) in H×W
                let displayBox: CGRect = isLandscape
                    ? CGRect(
                        x: pixelBox.origin.y,
                        y: imageSize.width - pixelBox.origin.x - pixelBox.width,
                        width: pixelBox.height,
                        height: pixelBox.width
                      )
                    : pixelBox
                
                let screenBox = CGRect(
                    x: displayBox.origin.x * scale - offsetX,
                    y: displayBox.origin.y * scale - offsetY,
                    width: displayBox.width * scale,
                    height: displayBox.height * scale
                )
                
                TargetBoundingBoxView(
                    targetRect: screenBox,
                    targetState: target.state,
                    isActive: activeTarget?.id == target.id,
                    classificationResult: activeTarget?.id == target.id ? classificationResult : nil,
                    visibility: target.visibility
                )
            }
        }
    }
}

/// 单个目标边界框视图
struct TargetBoundingBoxView: View {
    let targetRect: CGRect
    let targetState: TargetState
    let isActive: Bool
    let classificationResult: ClassificationResult?
    let visibility: Double
    
    @State private var pulseOpacity: Double = 0.8
    @State private var dashPhase: CGFloat = 0
    
    var body: some View {
        ZStack {
            // 边界框 - 使用虚线动画效果
            Rectangle()
                .stroke(
                    markerColor,
                    style: StrokeStyle(
                        lineWidth: lineWidth,
                        lineCap: .round,
                        lineJoin: .round,
                        dash: [8, 4],
                        dashPhase: dashPhase
                    )
                )
                .frame(width: targetRect.width + padding, height: targetRect.height + padding)
                .opacity(pulseOpacity)
            
            // 四角标记
            CornerMarkers(size: CGSize(width: targetRect.width + padding, height: targetRect.height + padding), color: markerColor, lineWidth: lineWidth)
            
            // 状态标签
            if targetState == .confirmed || targetState == .engaging {
                statusLabel
                    .offset(y: -(targetRect.height / 2 + padding / 2 + 20))
            }
            
            // 被排除的目标显示叉号
            if targetState == .dismissed {
                Image(systemName: "xmark")
                    .font(.system(size: min(targetRect.width, targetRect.height) * 0.4, weight: .bold))
                    .foregroundColor(.gray)
            }
        }
        .position(x: targetRect.midX, y: targetRect.midY)
        .opacity(visibility)
        .onAppear {
            startAnimations()
        }
        .onChange(of: targetState) { _, _ in
            startAnimations()
        }
    }
    
    // MARK: - Status Label
    
    private var statusLabel: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(markerColor)
                .frame(width: 8, height: 8)
            
            Text(statusText)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundColor(markerColor)
            
            if let result = classificationResult, targetState == .confirmed {
                Text(result.confidencePercentage)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(.white)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.black.opacity(0.8))
        .cornerRadius(4)
    }
    
    // MARK: - Computed Properties
    
    private var markerColor: Color {
        switch targetState {
        case .suspect:
            return .yellow
        case .engaging:
            return .orange
        case .confirmed:
            return .red
        case .dismissed:
            return .gray
        }
    }
    
    private var statusText: String {
        switch targetState {
        case .suspect:
            return "可疑"
        case .engaging:
            return "确认中..."
        case .confirmed:
            return "蚊子!"
        case .dismissed:
            return "已排除"
        }
    }
    
    private var lineWidth: CGFloat {
        switch targetState {
        case .confirmed:
            return 3
        case .engaging:
            return 2.5
        default:
            return 2
        }
    }
    
    private var padding: CGFloat {
        return 16
    }
    
    // MARK: - Animations
    
    private func startAnimations() {
        // 透明度脉冲
        withAnimation(
            Animation.easeInOut(duration: 0.8)
                .repeatForever(autoreverses: true)
        ) {
            pulseOpacity = 0.4
        }
        
        // 虚线流动动画
        withAnimation(
            Animation.linear(duration: 1.0)
                .repeatForever(autoreverses: false)
        ) {
            dashPhase = 24
        }
    }
}

/// 四角标记
struct CornerMarkers: View {
    let size: CGSize
    let color: Color
    let lineWidth: CGFloat
    
    private let cornerLength: CGFloat = 15
    
    var body: some View {
        ZStack {
            // 左上角
            CornerMark(rotation: 0)
                .offset(x: -size.width / 2, y: -size.height / 2)
            
            // 右上角
            CornerMark(rotation: 90)
                .offset(x: size.width / 2, y: -size.height / 2)
            
            // 右下角
            CornerMark(rotation: 180)
                .offset(x: size.width / 2, y: size.height / 2)
            
            // 左下角
            CornerMark(rotation: 270)
                .offset(x: -size.width / 2, y: size.height / 2)
        }
    }
    
    @ViewBuilder
    private func CornerMark(rotation: Double) -> some View {
        Path { path in
            path.move(to: CGPoint(x: 0, y: cornerLength))
            path.addLine(to: CGPoint(x: 0, y: 0))
            path.addLine(to: CGPoint(x: cornerLength, y: 0))
        }
        .stroke(color, style: StrokeStyle(lineWidth: lineWidth + 1, lineCap: .round, lineJoin: .round))
        .rotationEffect(.degrees(rotation))
    }
}

#Preview {
    ZStack {
        Color.black.ignoresSafeArea()
        
        TargetOverlayView(
            targets: [
                TrackedTarget(boundingBox: CGRect(x: 100, y: 200, width: 80, height: 60), state: .suspect),
                TrackedTarget(boundingBox: CGRect(x: 220, y: 400, width: 100, height: 80), state: .confirmed)
            ],
            activeTarget: nil,
            classificationResult: ClassificationResult(isMosquito: true, confidence: 0.95),
            imageSize: CGSize(width: 1080, height: 1920)
        )
    }
}
