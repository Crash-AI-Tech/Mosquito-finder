import SwiftUI

/// 雷达脉冲动画 — 多圈同心扩散
struct RadarPulseView: View {
    @State private var animate = false

    var body: some View {
        ZStack {
            ForEach(0..<4, id: \.self) { i in
                Circle()
                    .stroke(Color.green.opacity(animate ? 0 : 0.6), lineWidth: 1.5)
                    .scaleEffect(animate ? 2.2 : 0.3)
                    .animation(
                        .easeOut(duration: 2.4)
                        .repeatForever(autoreverses: false)
                        .delay(Double(i) * 0.6),
                        value: animate
                    )
            }
        }
        .onAppear { animate = true }
    }
}

/// 扫描线动画 — 从上到下循环扫
struct ScanLineView: View {
    @State private var offset: CGFloat = -1

    var body: some View {
        GeometryReader { geo in
            Rectangle()
                .fill(
                    LinearGradient(
                        colors: [.clear, .green.opacity(0.35), .clear],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .frame(height: 60)
                .offset(y: offset * geo.size.height)
                .onAppear {
                    withAnimation(
                        .linear(duration: 3.5)
                        .repeatForever(autoreverses: false)
                    ) {
                        offset = 1.2
                    }
                }
        }
        .allowsHitTesting(false)
        .clipped()
    }
}

/// 军事风格四角准星
struct TacticalCrosshair: View {
    var isLocked: Bool
    var hasTarget: Bool
    @State private var pulse = false

    private var ringColor: Color {
        if isLocked { return .red }
        if hasTarget { return .orange }
        return .green
    }

    var body: some View {
        ZStack {
            // 外圈脉冲（锁定时）
            if isLocked {
                Circle()
                    .stroke(Color.red.opacity(pulse ? 0 : 0.5), lineWidth: 2)
                    .frame(width: 130, height: 130)
                    .scaleEffect(pulse ? 1.6 : 1.0)
                    .animation(.easeOut(duration: 0.9).repeatForever(autoreverses: false), value: pulse)
                    .onAppear { pulse = true }
                    .onDisappear { pulse = false }
            }

            // 主环
            Circle()
                .stroke(ringColor.opacity(0.45), lineWidth: 1)
                .frame(width: 110, height: 110)

            // 四角括号（军事瞄准镜风格）— 坐标以视图中心(80,80)为原点
            let cx: CGFloat = 80
            let cy: CGFloat = 80
            let armLen: CGFloat = 22
            let gap: CGFloat = 14
            let thick: CGFloat = 2

            // 左上
            Path { p in
                p.move(to: CGPoint(x: cx - gap - armLen, y: cy - gap))
                p.addLine(to: CGPoint(x: cx - gap, y: cy - gap))
                p.addLine(to: CGPoint(x: cx - gap, y: cy - gap - armLen))
            }
            .stroke(ringColor, style: StrokeStyle(lineWidth: thick, lineCap: .square))

            // 右上
            Path { p in
                p.move(to: CGPoint(x: cx + gap + armLen, y: cy - gap))
                p.addLine(to: CGPoint(x: cx + gap, y: cy - gap))
                p.addLine(to: CGPoint(x: cx + gap, y: cy - gap - armLen))
            }
            .stroke(ringColor, style: StrokeStyle(lineWidth: thick, lineCap: .square))

            // 左下
            Path { p in
                p.move(to: CGPoint(x: cx - gap - armLen, y: cy + gap))
                p.addLine(to: CGPoint(x: cx - gap, y: cy + gap))
                p.addLine(to: CGPoint(x: cx - gap, y: cy + gap + armLen))
            }
            .stroke(ringColor, style: StrokeStyle(lineWidth: thick, lineCap: .square))

            // 右下
            Path { p in
                p.move(to: CGPoint(x: cx + gap + armLen, y: cy + gap))
                p.addLine(to: CGPoint(x: cx + gap, y: cy + gap))
                p.addLine(to: CGPoint(x: cx + gap, y: cy + gap + armLen))
            }
            .stroke(ringColor, style: StrokeStyle(lineWidth: thick, lineCap: .square))

            // 细十字线
            Rectangle()
                .fill(ringColor.opacity(0.5))
                .frame(width: 1, height: 50)
            Rectangle()
                .fill(ringColor.opacity(0.5))
                .frame(width: 50, height: 1)

            // 中心点
            Circle()
                .fill(ringColor)
                .frame(width: 5, height: 5)
        }
        .frame(width: 160, height: 160)
        .animation(.easeInOut(duration: 0.3), value: isLocked)
        .animation(.easeInOut(duration: 0.3), value: hasTarget)
    }
}

/// 竖向刻度尺（左侧/右侧各一条）
struct SideRuler: View {
    var isLeft: Bool

    var body: some View {
        VStack(spacing: 0) {
            ForEach(0..<20, id: \.self) { i in
                HStack(spacing: 3) {
                    if isLeft {
                        Rectangle()
                            .fill(Color.green.opacity(i % 5 == 0 ? 0.7 : 0.3))
                            .frame(width: i % 5 == 0 ? 12 : 6, height: 1)
                        if i % 5 == 0 {
                            Text("\(i * 5)")
                                .font(.system(size: 7, design: .monospaced))
                                .foregroundColor(.green.opacity(0.6))
                        }
                    } else {
                        if i % 5 == 0 {
                            Text("\(i * 5)")
                                .font(.system(size: 7, design: .monospaced))
                                .foregroundColor(.green.opacity(0.6))
                        }
                        Rectangle()
                            .fill(Color.green.opacity(i % 5 == 0 ? 0.7 : 0.3))
                            .frame(width: i % 5 == 0 ? 12 : 6, height: 1)
                    }
                }
                .frame(height: 14)
            }
        }
    }
}
