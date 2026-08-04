import SwiftUI

struct StationaryDetectionView: View {
    @StateObject private var viewModel = StationaryDetectionViewModel()
    let onClose: () -> Void
    let onContinueCloseUp: () -> Void

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color.black.ignoresSafeArea()

                CameraPreviewView(session: viewModel.cameraController.captureSession)
                    .ignoresSafeArea()

                if let frozenFrame = viewModel.frozenFrame {
                    Image(uiImage: frozenFrame)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .clipped()
                        .ignoresSafeArea()
                }

                Color.green.opacity(viewModel.frozenFrame == nil ? 0.025 : 0)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)

                FlightTrackOverlay(
                    tracks: viewModel.tracks,
                    primaryTrackID: viewModel.primaryTrack?.id,
                    landingCandidate: viewModel.landingCandidate,
                    imageSize: viewModel.nativeImageSize
                )
                .ignoresSafeArea()
                .allowsHitTesting(false)

                VStack(spacing: 0) {
                    topBar
                        .padding(.horizontal, 16)
                        .padding(.top, 12)

                    if viewModel.phase == .calibrating || viewModel.phase == .positioning || viewModel.phase == .cameraMoved {
                        calibrationPanel
                            .padding(.horizontal, 28)
                            .padding(.top, 18)
                    }

                    Spacer()

                    if viewModel.landingCandidate != nil {
                        landingPanel
                            .padding(.horizontal, 16)
                            .padding(.bottom, 28)
                    } else {
                        monitoringPanel
                            .padding(.horizontal, 16)
                            .padding(.bottom, 28)
                    }
                }

                if let errorMessage = viewModel.errorMessage {
                    errorPanel(errorMessage)
                }
            }
        }
        .preferredColorScheme(.dark)
        .statusBarHidden()
        .onAppear { viewModel.start() }
        .onDisappear { viewModel.stop() }
    }

    private var topBar: some View {
        HStack(spacing: 10) {
            Button {
                viewModel.stop()
                onClose()
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundColor(.white)
                    .frame(width: 36, height: 36)
                    .background(.ultraThinMaterial)
                    .clipShape(Circle())
            }
            .accessibilityLabel(Text("Close"))

            HStack(spacing: 7) {
                Circle()
                    .fill(viewModel.phase.tint)
                    .frame(width: 7, height: 7)
                Text("Tripod watch")
                    .font(.system(size: 12, weight: .semibold))
                Text(viewModel.elapsedTime)
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundColor(.white.opacity(0.58))
            }
            .foregroundColor(.white)
            .padding(.horizontal, 11)
            .frame(height: 36)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            Spacer()

            HStack(spacing: 6) {
                Image(systemName: "point.3.connected.trianglepath.dotted")
                Text("\(viewModel.diagnostics.qualifiedTrackCount)")
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
            }
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(viewModel.diagnostics.qualifiedTrackCount > 0 ? .orange : .white.opacity(0.55))
            .padding(.horizontal, 11)
            .frame(height: 36)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }

    private var calibrationPanel: some View {
        HStack(spacing: 13) {
            ZStack {
                Circle()
                    .fill(viewModel.phase.tint.opacity(0.16))
                Image(systemName: viewModel.phase.systemImage)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(viewModel.phase.tint)
            }
            .frame(width: 42, height: 42)

            VStack(alignment: .leading, spacing: 5) {
                Text(viewModel.phase.titleKey)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundColor(.white)
                Text(viewModel.phase.detailKey)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white.opacity(0.66))
                    .fixedSize(horizontal: false, vertical: true)

                if viewModel.phase == .calibrating {
                    ProgressView(value: viewModel.diagnostics.calibrationProgress)
                        .tint(.cyan)
                }
            }

            Spacer(minLength: 0)
        }
        .padding(14)
        .background(.ultraThinMaterial)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(viewModel.phase.tint.opacity(0.34), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var monitoringPanel: some View {
        VStack(spacing: 12) {
            HStack(alignment: .top, spacing: 11) {
                Image(systemName: viewModel.phase.systemImage)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(viewModel.phase.tint)
                    .frame(width: 28)

                VStack(alignment: .leading, spacing: 3) {
                    Text(viewModel.phase.titleKey)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundColor(.white)
                    Text(viewModel.phase.detailKey)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white.opacity(0.64))
                        .lineLimit(2)
                }

                Spacer(minLength: 4)

                if viewModel.phase == .trackingFlight {
                    ProgressView()
                        .tint(.orange)
                }
            }
            .padding(12)
            .background(.ultraThinMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(viewModel.phase.tint.opacity(0.3), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            HStack(spacing: 8) {
                monitorMetric(icon: "camera", value: cameraRateText, tint: .cyan)
                monitorMetric(icon: "waveform.path", value: "\(viewModel.diagnostics.foregroundRegionCount)", tint: .yellow)
                monitorMetric(icon: "timer", value: viewModel.diagnostics.processingTimeText, tint: .green)

                Button {
                    viewModel.toggleFlashlight()
                } label: {
                    Image(systemName: viewModel.isFlashlightOn ? "flashlight.on.fill" : "flashlight.off.fill")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundColor(viewModel.isFlashlightOn ? .yellow : .white.opacity(0.55))
                        .frame(width: 42, height: 38)
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .accessibilityLabel(Text("Light"))

                Button {
                    viewModel.recalibrate()
                } label: {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.white.opacity(0.62))
                        .frame(width: 42, height: 38)
                        .background(.ultraThinMaterial)
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .accessibilityLabel(Text("Recalibrate"))
            }
        }
    }

    private var landingPanel: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle().fill(viewModel.phase.tint.opacity(0.16))
                    Image(systemName: viewModel.phase.systemImage)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundColor(viewModel.phase.tint)
                }
                .frame(width: 42, height: 42)

                VStack(alignment: .leading, spacing: 4) {
                    Text(viewModel.phase.titleKey)
                        .font(.system(size: 17, weight: .bold))
                        .foregroundColor(.white)
                    Text(viewModel.phase.detailKey)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.white.opacity(0.66))
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 4)

                if viewModel.phase == .verifying {
                    ProgressView().tint(.cyan)
                } else if let result = viewModel.classificationResult {
                    Text(result.confidencePercentage)
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundColor(result.isMosquito ? .red : .yellow)
                }
            }

            Button {
                viewModel.stop()
                onContinueCloseUp()
            } label: {
                HStack(spacing: 9) {
                    Image(systemName: "figure.walk.motion")
                    Text("Continue with close-up scan")
                }
                .font(.system(size: 15, weight: .bold))
                .foregroundColor(.black)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .background(Color.green)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .disabled(viewModel.phase == .verifying)

            HStack(spacing: 10) {
                Button {
                    viewModel.markFalseAlarmAndResume()
                } label: {
                    Label("False alarm", systemImage: "xmark.circle")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(StationarySecondaryButtonStyle())

                Button {
                    viewModel.recalibrate()
                } label: {
                    Label("Resume watch", systemImage: "arrow.counterclockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(StationarySecondaryButtonStyle())
            }
        }
        .padding(14)
        .background(.ultraThinMaterial)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(viewModel.phase.tint.opacity(0.36), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private var cameraRateText: String {
        let fps = viewModel.cameraController.activeFramesPerSecond
        return fps > 0 ? String(format: "%.0ffps", fps) : "--fps"
    }

    private func monitorMetric(icon: String, value: String, tint: Color) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
            Text(value)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .font(.system(size: 10, weight: .semibold))
        .foregroundColor(tint)
        .frame(maxWidth: .infinity)
        .frame(height: 38)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func errorPanel(_ error: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 28))
                .foregroundColor(.orange)
            Text(error)
                .font(.system(size: 13, weight: .medium))
                .multilineTextAlignment(.center)
                .foregroundColor(.white)
            Button("Close") {
                viewModel.stop()
                onClose()
            }
            .buttonStyle(.borderedProminent)
            .tint(.orange)
        }
        .padding(20)
        .frame(maxWidth: 280)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct StationarySecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundColor(.white.opacity(configuration.isPressed ? 0.55 : 0.78))
            .frame(height: 42)
            .background(Color.white.opacity(configuration.isPressed ? 0.05 : 0.09))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct FlightTrackOverlay: View {
    let tracks: [FlightTrackSnapshot]
    let primaryTrackID: UUID?
    let landingCandidate: LandingCandidate?
    let imageSize: CGSize

    var body: some View {
        GeometryReader { geometry in
            Canvas { context, size in
                for track in tracks {
                    let isPrimary = track.id == primaryTrackID
                    let color: Color = track.isFlightLike ? .orange : .yellow.opacity(0.72)
                    let projectedPoints = track.points.map { project($0, into: size) }

                    if projectedPoints.count > 1 {
                        var path = Path()
                        path.move(to: projectedPoints[0])
                        for point in projectedPoints.dropFirst() {
                            path.addLine(to: point)
                        }
                        context.stroke(
                            path,
                            with: .color(color.opacity(isPrimary ? 0.9 : 0.5)),
                            style: StrokeStyle(lineWidth: isPrimary ? 2.2 : 1.2, lineCap: .round, lineJoin: .round)
                        )
                    }

                    let rect = projected(track.boundingBox, into: size)
                    context.stroke(
                        Path(ellipseIn: rect),
                        with: .color(color.opacity(isPrimary ? 0.95 : 0.55)),
                        lineWidth: isPrimary ? 2 : 1
                    )
                }

                if let landingCandidate {
                    let rect = projected(landingCandidate.boundingBox, into: size)
                    let center = CGPoint(x: rect.midX, y: rect.midY)
                    let radius = max(30, min(rect.width, rect.height) * 0.48)
                    let outer = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
                    context.stroke(Path(ellipseIn: outer), with: .color(.yellow), lineWidth: 3)
                    context.stroke(Path(ellipseIn: outer.insetBy(dx: 10, dy: 10)), with: .color(.yellow.opacity(0.55)), lineWidth: 1)

                    var cross = Path()
                    cross.move(to: CGPoint(x: center.x - 10, y: center.y))
                    cross.addLine(to: CGPoint(x: center.x + 10, y: center.y))
                    cross.move(to: CGPoint(x: center.x, y: center.y - 10))
                    cross.addLine(to: CGPoint(x: center.x, y: center.y + 10))
                    context.stroke(cross, with: .color(.yellow), lineWidth: 2)
                }
            }
        }
    }

    private func project(_ point: CGPoint, into screenSize: CGSize) -> CGPoint {
        let rect = projected(CGRect(x: point.x, y: point.y, width: 0, height: 0), into: screenSize)
        return rect.origin
    }

    private func projected(_ rect: CGRect, into screenSize: CGSize) -> CGRect {
        guard imageSize.width > 0, imageSize.height > 0 else { return .zero }
        let isLandscape = imageSize.width > imageSize.height
        let displaySize = isLandscape
            ? CGSize(width: imageSize.height, height: imageSize.width)
            : imageSize
        let displayRect = isLandscape
            ? CGRect(
                x: rect.origin.y,
                y: imageSize.width - rect.origin.x - rect.width,
                width: rect.height,
                height: rect.width
            )
            : rect
        let scale = max(screenSize.width / displaySize.width, screenSize.height / displaySize.height)
        let offsetX = (displaySize.width * scale - screenSize.width) / 2
        let offsetY = (displaySize.height * scale - screenSize.height) / 2
        return CGRect(
            x: displayRect.origin.x * scale - offsetX,
            y: displayRect.origin.y * scale - offsetY,
            width: max(1, displayRect.width * scale),
            height: max(1, displayRect.height * scale)
        )
    }
}
