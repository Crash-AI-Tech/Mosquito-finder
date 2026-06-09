import SwiftUI

struct MainTabView: View {
    @State private var selectedTab = 0
    @AppStorage("appLanguage") private var appLanguage: String = ""

    private var currentLocale: Locale {
        switch appLanguage {
        case "en": return Locale(identifier: "en_US")
        case "zh-Hans": return Locale(identifier: "zh-Hans")
        default:
            let code = Locale.current.language.languageCode?.identifier ?? "en"
            return code.hasPrefix("zh") ? Locale(identifier: "zh-Hans") : Locale(identifier: "en_US")
        }
    }
    
    var body: some View {
        TabView(selection: $selectedTab) {
            // Tab 1: 雷达 (主功能)
            HuntingView()
                .tabItem {
                    Image(systemName: "camera.viewfinder")
                    Text("Radar")
                }
                .tag(0)
            
            // Tab 2: 战绩
            TrophyView()
                .tabItem {
                    Image(systemName: "target")
                    Text("Trophy")
                }
                .tag(1)
            
            // Tab 3: 设置
            SettingsView()
                .tabItem {
                    Image(systemName: "gearshape")
                    Text("Settings")
                }
                .tag(2)
        }
        .tint(.red)
        .preferredColorScheme(.dark)
        .environment(\.locale, currentLocale)
    }
}

struct TrophyView: View {
    @ObservedObject private var statsStore = HuntingStatsStore.shared

    var body: some View {
        NavigationView {
            List {
                Section {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 2), spacing: 12) {
                        statTile(title: "Total Mosquitoes", value: "\(statsStore.snapshot.totalMosquitoes)", tint: .red)
                        statTile(title: "Total Hunts", value: "\(statsStore.snapshot.sessionCount)", tint: .green)
                        statTile(title: "Best Confidence", value: percentText(statsStore.snapshot.bestConfidence), tint: .orange)
                        statTile(title: "Total Time", value: durationText(statsStore.snapshot.totalDuration), tint: .cyan)
                    }
                    .padding(.vertical, 8)
                }

                Section(header: Text("Recent Hunts")) {
                    if statsStore.sessions.isEmpty {
                        Text("No records yet. Start hunting!")
                            .foregroundColor(.gray)
                            .padding(.vertical, 20)
                    } else {
                        ForEach(statsStore.sessions.prefix(12)) { session in
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    Text(session.endedAt, style: .date)
                                    Text(session.endedAt, style: .time)
                                    Spacer()
                                    Text("\(session.confirmedMosquitoes)")
                                        .font(.system(.headline, design: .monospaced))
                                        .foregroundColor(session.confirmedMosquitoes > 0 ? .red : .gray)
                                }
                                HStack(spacing: 10) {
                                    Text(String(format: NSLocalizedString("%lld suspects", comment: ""), session.suspectsFound))
                                    Text(durationText(session.duration))
                                    Text(session.modelMode.localizedDisplayNameKey)
                                }
                                .font(.caption)
                                .foregroundColor(.gray)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                Section(header: Text("Confirmed Targets")) {
                    if statsStore.hits.isEmpty {
                        Text("No confirmed targets yet.")
                            .foregroundColor(.gray)
                            .padding(.vertical, 12)
                    } else {
                        ForEach(statsStore.hits.prefix(20)) { hit in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(hit.timestamp, style: .date)
                                    Text(hit.modelMode.localizedDisplayNameKey)
                                        .font(.caption)
                                        .foregroundColor(.gray)
                                }
                                Spacer()
                                Text(percentText(hit.confidence))
                                    .font(.system(.body, design: .monospaced))
                                    .foregroundColor(.green)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Trophies")
        }
    }

    private func statTile(title: LocalizedStringKey, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundColor(.gray)
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .monospaced))
                .foregroundColor(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.white.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func percentText(_ value: Float) -> String {
        value > 0 ? String(format: "%.0f%%", value * 100) : "--"
    }

    private func durationText(_ duration: TimeInterval) -> String {
        let totalSeconds = Int(duration.rounded())
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }
}

struct SettingsView: View {
    @AppStorage("enableHaptics") private var enableHaptics = true
    @AppStorage("autoFlashlight") private var autoFlashlight = true
    @AppStorage("appLanguage") private var appLanguage: String = ""
    @AppStorage("detectionModelMode") private var detectionModelMode = RuntimeModelMode.preferredDefault.rawValue
    @AppStorage("stage2ConfidenceThreshold") private var stage2ConfidenceThreshold = Double(RuntimeDetectionSettings.current.stage2ConfidenceThreshold)
    @AppStorage("minZoomFactor") private var minZoomFactor = Double(RuntimeDetectionSettings.current.minZoomFactor)
    @AppStorage("centerRegionRatio") private var centerRegionRatio = Double(RuntimeDetectionSettings.current.centerRegionRatio)
    @AppStorage("minTargetSize") private var minTargetSize = Double(RuntimeDetectionSettings.current.minTargetSize)
    @AppStorage("stableFrameCount") private var stableFrameCount = RuntimeDetectionSettings.current.stableFrameCount
    @AppStorage("stage2Cooldown") private var stage2Cooldown = RuntimeDetectionSettings.current.stage2Cooldown
    @AppStorage("maxStage1Detections") private var maxStage1Detections = RuntimeDetectionSettings.current.maxStage1Detections
    @AppStorage("stage1LocalContrastThreshold") private var stage1LocalContrastThreshold = Double(RuntimeDetectionSettings.current.stage1LocalContrastThreshold)
    @AppStorage("stage1BackgroundVarianceThreshold") private var stage1BackgroundVarianceThreshold = Double(RuntimeDetectionSettings.current.stage1BackgroundVarianceThreshold)
    @AppStorage("detectorNmsIouThreshold") private var detectorNmsIouThreshold = Double(RuntimeDetectionSettings.current.detectorNmsIouThreshold)

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 14) {
                    detectionProfileSection
                    pipelineSection
                    commonSection
                    tuningSection
                    modelInventorySection
                    appSection
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 18)
            }
            .background(Color.black.ignoresSafeArea())
            .navigationTitle("Settings")
            .onAppear {
                validateSelectedModel()
            }
        }
    }

    private var selectedModelMode: RuntimeModelMode {
        RuntimeModelMode(rawValue: detectionModelMode) ?? .coreMLStrict
    }

    private var orderedProfiles: [RuntimeModelMode] {
        [.detectorDfine, .detectorYolox, .coreMLBalanced, .coreMLStrict]
    }

    private var detectionProfileSection: some View {
        SettingsPanel(title: "Detection Profile", systemImage: "scope") {
            VStack(spacing: 10) {
                ForEach(orderedProfiles) { mode in
                    Button {
                        guard mode.isBundled && mode.isProductionReady else { return }
                        applyPreset(mode)
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: profileIcon(for: mode))
                                .font(.system(size: 18, weight: .semibold))
                                .foregroundColor(profileColor(for: mode))
                                .frame(width: 28)

                            VStack(alignment: .leading, spacing: 4) {
                                HStack(spacing: 6) {
                                    Text(profileTitle(for: mode))
                                        .font(.subheadline.weight(.semibold))
                                        .foregroundColor(.primary)
                                    if mode == .detectorDfine {
                                        Text("Recommended")
                                            .font(.caption2.weight(.bold))
                                            .foregroundColor(.black)
                                            .padding(.horizontal, 6)
                                            .padding(.vertical, 2)
                                            .background(Color.green)
                                            .clipShape(Capsule())
                                    }
                                }
                                Text(profileSubtitle(for: mode))
                                    .font(.caption)
                                    .foregroundColor(.gray)
                                    .lineLimit(2)
                            }

                            Spacer()

                            if selectedModelMode == mode {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundColor(.green)
                            } else {
                                Text(mode.isBundled ? "Select" : "Missing")
                                    .font(.caption.weight(.semibold))
                                    .foregroundColor(mode.isBundled ? .gray : .orange)
                            }
                        }
                        .padding(12)
                        .background(profileBackground(for: mode))
                        .overlay(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .stroke(selectedModelMode == mode ? profileColor(for: mode).opacity(0.8) : Color.white.opacity(0.08), lineWidth: 1)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        .opacity(mode.isBundled && mode.isProductionReady ? 1 : 0.55)
                    }
                    .buttonStyle(.plain)
                    .disabled(!mode.isBundled || !mode.isProductionReady)
                }
            }
        }
    }

    private var pipelineSection: some View {
        SettingsPanel(title: "Current Pipeline", systemImage: "point.3.connected.trianglepath.dotted") {
            VStack(spacing: 12) {
                pipelineStageRow(
                    number: "1",
                    title: "Candidate Generation",
                    value: stage1PipelineName(for: selectedModelMode),
                    detail: stage1PipelineDetail(for: selectedModelMode),
                    tint: .orange
                )

                Divider().overlay(Color.white.opacity(0.08))

                pipelineStageRow(
                    number: "2",
                    title: "Confirmation",
                    value: stage2PipelineName(for: selectedModelMode),
                    detail: stage2PipelineDetail(for: selectedModelMode),
                    tint: .green
                )

                Divider().overlay(Color.white.opacity(0.08))

                HStack(spacing: 8) {
                    parameterChip(title: "Confirm", value: percentText(stage2ConfidenceThreshold), tint: .green)
                    parameterChip(title: "Stable", value: "\(stableFrameCount)f", tint: .cyan)
                    parameterChip(title: "Candidates", value: "\(maxStage1Detections)", tint: .orange)
                }
            }
        }
    }

    private var commonSection: some View {
        SettingsPanel(title: "Common Controls", systemImage: "slider.horizontal.3") {
            VStack(spacing: 12) {
                Toggle(isOn: $autoFlashlight) {
                    Label("Auto Flashlight", systemImage: "flashlight.on.fill")
                }
                .tint(.green)

                Toggle(isOn: $enableHaptics) {
                    Label("Haptic Feedback", systemImage: "iphone.radiowaves.left.and.right")
                }
                .tint(.green)

                Picker("App Language", selection: $appLanguage) {
                    Text("Follow System").tag("")
                    Text("English").tag("en")
                    Text("Simplified Chinese").tag("zh-Hans")
                }
                .pickerStyle(.menu)
            }
        }
    }

    private var tuningSection: some View {
        SettingsPanel(title: "Tune Pipeline", systemImage: "wrench.adjustable") {
            VStack(spacing: 10) {
                NavigationLink {
                    Stage1TuningView(
                        mode: selectedModelMode,
                        maxStage1Detections: $maxStage1Detections,
                        stage1LocalContrastThreshold: $stage1LocalContrastThreshold,
                        stage1BackgroundVarianceThreshold: $stage1BackgroundVarianceThreshold,
                        detectorNmsIouThreshold: $detectorNmsIouThreshold
                    )
                } label: {
                    tuningRow(
                        title: "Stage 1",
                        subtitle: stage1PipelineName(for: selectedModelMode),
                        systemImage: "viewfinder",
                        tint: .orange
                    )
                }

                NavigationLink {
                    Stage2TuningView(
                        mode: selectedModelMode,
                        stage2ConfidenceThreshold: $stage2ConfidenceThreshold,
                        stableFrameCount: $stableFrameCount,
                        stage2Cooldown: $stage2Cooldown
                    )
                } label: {
                    tuningRow(
                        title: "Stage 2",
                        subtitle: stage2PipelineName(for: selectedModelMode),
                        systemImage: "checkmark.seal",
                        tint: .green
                    )
                }

                NavigationLink {
                    TriggerTuningView(
                        minZoomFactor: $minZoomFactor,
                        centerRegionRatio: $centerRegionRatio,
                        minTargetSize: $minTargetSize
                    )
                } label: {
                    tuningRow(
                        title: "Trigger Gates",
                        subtitle: "Center, zoom, and target size",
                        systemImage: "dot.scope",
                        tint: .cyan
                    )
                }

                NavigationLink {
                    PipelineDiagnosticsView(
                        mode: selectedModelMode,
                        stage2ConfidenceThreshold: stage2ConfidenceThreshold,
                        minZoomFactor: minZoomFactor,
                        centerRegionRatio: centerRegionRatio,
                        minTargetSize: minTargetSize,
                        stableFrameCount: stableFrameCount,
                        stage2Cooldown: stage2Cooldown,
                        maxStage1Detections: maxStage1Detections,
                        stage1LocalContrastThreshold: stage1LocalContrastThreshold,
                        stage1BackgroundVarianceThreshold: stage1BackgroundVarianceThreshold,
                        detectorNmsIouThreshold: detectorNmsIouThreshold
                    )
                } label: {
                    tuningRow(
                        title: "Developer Diagnostics",
                        subtitle: "Runtime values and model inventory",
                        systemImage: "terminal",
                        tint: .purple
                    )
                }
            }
            .buttonStyle(.plain)
        }
    }

    private var modelInventorySection: some View {
        SettingsPanel(title: "Model Inventory", systemImage: "shippingbox") {
            VStack(spacing: 12) {
                ModelStatusRow(mode: .detectorDfine)
                ModelStatusRow(mode: .detectorYolox)
                ModelStatusRow(mode: .coreMLBalanced)
                ModelStatusRow(mode: .coreMLStrict)
            }
        }
    }

    private var appSection: some View {
        SettingsPanel(title: "About", systemImage: "info.circle") {
            settingsValueRow(title: "Version", value: "1.0.0", systemImage: "app.badge")
        }
    }

    private func validateSelectedModel() {
        if !selectedModelMode.isBundled || !selectedModelMode.isProductionReady {
            applyPreset(RuntimeModelMode.preferredDefault)
        }
    }

    private func applyPreset(_ mode: RuntimeModelMode) {
        RuntimeDetectionSettings.applyPreset(mode)
        detectionModelMode = mode.rawValue
        let settings = RuntimeDetectionSettings.current
        stage2ConfidenceThreshold = Double(settings.stage2ConfidenceThreshold)
        minZoomFactor = Double(settings.minZoomFactor)
        centerRegionRatio = Double(settings.centerRegionRatio)
        minTargetSize = Double(settings.minTargetSize)
        stableFrameCount = settings.stableFrameCount
        stage2Cooldown = settings.stage2Cooldown
        maxStage1Detections = settings.maxStage1Detections
        stage1LocalContrastThreshold = Double(settings.stage1LocalContrastThreshold)
        stage1BackgroundVarianceThreshold = Double(settings.stage1BackgroundVarianceThreshold)
        detectorNmsIouThreshold = Double(settings.detectorNmsIouThreshold)
    }

    private func pipelineStageRow(
        number: String,
        title: String,
        value: String,
        detail: String,
        tint: Color
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Text(number)
                .font(.system(.caption, design: .monospaced).weight(.bold))
                .foregroundColor(.black)
                .frame(width: 24, height: 24)
                .background(tint)
                .clipShape(Circle())

            VStack(alignment: .leading, spacing: 4) {
                Text(title.uppercased())
                    .font(.caption2.weight(.semibold))
                    .foregroundColor(.gray)
                Text(value)
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.primary)
                Text(detail)
                    .font(.caption)
                    .foregroundColor(.gray)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)
        }
    }

    private func parameterChip(title: String, value: String, tint: Color) -> some View {
        VStack(spacing: 3) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundColor(.gray)
            Text(value)
                .font(.system(.caption, design: .monospaced).weight(.bold))
                .foregroundColor(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        .background(Color.white.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func tuningRow(title: String, subtitle: String, systemImage: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(tint)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(.primary)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundColor(.gray)
        }
        .padding(12)
        .background(Color.white.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func settingsValueRow(title: String, value: String, systemImage: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: systemImage)
                .foregroundColor(.gray)
                .frame(width: 24)
            Text(title)
            Spacer()
            Text(value)
                .foregroundColor(.gray)
                .font(.system(.footnote, design: .monospaced))
        }
    }

    private func profileTitle(for mode: RuntimeModelMode) -> String {
        switch mode {
        case .detectorDfine: return "D-FINE Two-Stage"
        case .detectorYolox: return "YOLOX High Precision"
        case .coreMLBalanced: return "Classic Balanced"
        case .coreMLStrict: return "Classic Strict"
        }
    }

    private func profileSubtitle(for mode: RuntimeModelMode) -> String {
        switch mode {
        case .detectorDfine:
            return "Full-frame detector, stable confidence confirmation."
        case .detectorYolox:
            return "Full-frame detector with tighter box suppression."
        case .coreMLBalanced:
            return "Dark-spot candidates, RGB CNN confirmation."
        case .coreMLStrict:
            return "Classic two-stage chain with fewer false positives."
        }
    }

    private func profileIcon(for mode: RuntimeModelMode) -> String {
        switch mode {
        case .detectorDfine: return "scope"
        case .detectorYolox: return "smallcircle.filled.circle"
        case .coreMLBalanced: return "circle.grid.cross"
        case .coreMLStrict: return "lock.shield"
        }
    }

    private func profileColor(for mode: RuntimeModelMode) -> Color {
        switch mode {
        case .detectorDfine: return .green
        case .detectorYolox: return .cyan
        case .coreMLBalanced: return .orange
        case .coreMLStrict: return .red
        }
    }

    private func profileBackground(for mode: RuntimeModelMode) -> Color {
        selectedModelMode == mode ? profileColor(for: mode).opacity(0.15) : Color.white.opacity(0.055)
    }

    private func stage1PipelineName(for mode: RuntimeModelMode) -> String {
        switch mode {
        case .detectorDfine: return "Full-frame D-FINE detector"
        case .detectorYolox: return "Full-frame YOLOX detector"
        case .coreMLBalanced, .coreMLStrict: return "Dark-spot candidate scanner"
        }
    }

    private func stage1PipelineDetail(for mode: RuntimeModelMode) -> String {
        switch mode {
        case .detectorDfine:
            return "Detector boxes become tracked candidates."
        case .detectorYolox:
            return "Detector boxes are filtered with NMS before tracking."
        case .coreMLBalanced, .coreMLStrict:
            return "Local contrast and smooth-background gates generate candidates."
        }
    }

    private func stage2PipelineName(for mode: RuntimeModelMode) -> String {
        mode.isDetectorMode ? "Stable detector confidence gate" : "RGB CNN classifier"
    }

    private func stage2PipelineDetail(for mode: RuntimeModelMode) -> String {
        mode.isDetectorMode
            ? "Tracked detector confidence must pass the confirmation threshold."
            : "The cropped target ROI is classified by MosquitoClassifier."
    }

    private func percentText(_ value: Double) -> String {
        String(format: "%.0f%%", value * 100)
    }
}

private struct SettingsPanel<Content: View>: View {
    let title: String
    let systemImage: String
    let content: Content

    init(title: String, systemImage: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.systemImage = systemImage
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label(title, systemImage: systemImage)
                .font(.headline.weight(.semibold))
                .foregroundColor(.primary)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.white.opacity(0.075))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct SettingSlider: View {
    let title: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let format: String
    var detail: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline)
                    if let detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundColor(.gray)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer()
                Text(String(format: format, value))
                    .foregroundColor(.gray)
                    .font(.system(.footnote, design: .monospaced))
            }
            Slider(value: $value, in: range)
                .tint(.green)
        }
        .padding(12)
        .background(Color.white.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct Stage1TuningView: View {
    let mode: RuntimeModelMode
    @Binding var maxStage1Detections: Int
    @Binding var stage1LocalContrastThreshold: Double
    @Binding var stage1BackgroundVarianceThreshold: Double
    @Binding var detectorNmsIouThreshold: Double

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SettingsPanel(title: "Stage 1", systemImage: "viewfinder") {
                    VStack(spacing: 12) {
                        Stepper("Max Candidates: \(maxStage1Detections)", value: $maxStage1Detections, in: 1...16)
                            .padding(12)
                            .background(Color.white.opacity(0.055))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                        if mode.isDetectorMode {
                            SettingSlider(
                                title: "Detector NMS IoU",
                                value: $detectorNmsIouThreshold,
                                range: 0.20...0.70,
                                format: "%.2f",
                                detail: mode == .detectorYolox ? "Used by YOLOX box suppression." : "Stored for detector profiles."
                            )

                            detectorThresholdRow
                        } else {
                            SettingSlider(
                                title: "Local Contrast",
                                value: $stage1LocalContrastThreshold,
                                range: 0.04...0.16,
                                format: "%.2f",
                                detail: "Minimum dark-point contrast against local background."
                            )

                            SettingSlider(
                                title: "Background Variance",
                                value: $stage1BackgroundVarianceThreshold,
                                range: 0.008...0.040,
                                format: "%.3f",
                                detail: "Lower values prefer smoother wall/background regions."
                            )
                        }
                    }
                }
            }
            .padding(16)
        }
        .background(Color.black.ignoresSafeArea())
        .navigationTitle("Stage 1")
    }

    private var detectorThresholdRow: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Candidate Threshold")
                .font(.subheadline)
            Text("Derived from Stage 2 confirmation threshold, capped at 0.35.")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(Color.white.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct Stage2TuningView: View {
    let mode: RuntimeModelMode
    @Binding var stage2ConfidenceThreshold: Double
    @Binding var stableFrameCount: Int
    @Binding var stage2Cooldown: Double

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SettingsPanel(title: "Stage 2", systemImage: "checkmark.seal") {
                    VStack(spacing: 12) {
                        SettingSlider(
                            title: mode.isDetectorMode ? "Detector Confirmation" : "CNN Mosquito Probability",
                            value: $stage2ConfidenceThreshold,
                            range: 0.50...0.99,
                            format: "%.2f",
                            detail: confidenceDetail
                        )

                        Stepper("Stable Frames: \(stableFrameCount)", value: $stableFrameCount, in: 2...12)
                            .padding(12)
                            .background(Color.white.opacity(0.055))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                        SettingSlider(
                            title: "Cooldown",
                            value: $stage2Cooldown,
                            range: 0.10...1.00,
                            format: "%.2fs",
                            detail: "Minimum time between confirmation attempts."
                        )
                    }
                }
            }
            .padding(16)
        }
        .background(Color.black.ignoresSafeArea())
        .navigationTitle("Stage 2")
    }

    private var confidenceDetail: String {
        mode.isDetectorMode
            ? "Uses the tracked full-frame detector confidence."
            : "Uses the MosquitoClassifier probability on the target ROI."
    }
}

private struct TriggerTuningView: View {
    @Binding var minZoomFactor: Double
    @Binding var centerRegionRatio: Double
    @Binding var minTargetSize: Double

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SettingsPanel(title: "Trigger Gates", systemImage: "dot.scope") {
                    VStack(spacing: 12) {
                        SettingSlider(
                            title: "Min Zoom",
                            value: $minZoomFactor,
                            range: 1.0...5.0,
                            format: "%.1fx",
                            detail: "Required camera zoom before confirmation can fire."
                        )

                        SettingSlider(
                            title: "Center Region",
                            value: $centerRegionRatio,
                            range: 0.15...0.60,
                            format: "%.2f",
                            detail: "Radius relative to the shorter frame edge."
                        )

                        SettingSlider(
                            title: "Min Target Size",
                            value: $minTargetSize,
                            range: 6...60,
                            format: "%.0fpx",
                            detail: "Smallest tracked box allowed to trigger confirmation."
                        )
                    }
                }
            }
            .padding(16)
        }
        .background(Color.black.ignoresSafeArea())
        .navigationTitle("Trigger Gates")
    }
}

private struct PipelineDiagnosticsView: View {
    let mode: RuntimeModelMode
    let stage2ConfidenceThreshold: Double
    let minZoomFactor: Double
    let centerRegionRatio: Double
    let minTargetSize: Double
    let stableFrameCount: Int
    let stage2Cooldown: Double
    let maxStage1Detections: Int
    let stage1LocalContrastThreshold: Double
    let stage1BackgroundVarianceThreshold: Double
    let detectorNmsIouThreshold: Double

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                SettingsPanel(title: "Runtime Values", systemImage: "terminal") {
                    VStack(spacing: 10) {
                        diagnosticRow("Mode", mode.displayName)
                        diagnosticRow("Pipeline", mode.isDetectorMode ? "Full-frame detector" : "Classic 2-stage")
                        diagnosticRow("Stage 2 Threshold", String(format: "%.2f", stage2ConfidenceThreshold))
                        diagnosticRow("Stable Frames", "\(stableFrameCount)")
                        diagnosticRow("Cooldown", String(format: "%.2fs", stage2Cooldown))
                        diagnosticRow("Max Stage 1 Candidates", "\(maxStage1Detections)")
                        diagnosticRow("Min Zoom", String(format: "%.1fx", minZoomFactor))
                        diagnosticRow("Center Region", String(format: "%.2f", centerRegionRatio))
                        diagnosticRow("Min Target Size", String(format: "%.0fpx", minTargetSize))
                        diagnosticRow("Local Contrast", String(format: "%.2f", stage1LocalContrastThreshold))
                        diagnosticRow("Background Variance", String(format: "%.3f", stage1BackgroundVarianceThreshold))
                        diagnosticRow("Detector NMS IoU", String(format: "%.2f", detectorNmsIouThreshold))
                    }
                }

                SettingsPanel(title: "Model Inventory", systemImage: "shippingbox") {
                    VStack(spacing: 12) {
                        ModelStatusRow(mode: .detectorDfine)
                        ModelStatusRow(mode: .detectorYolox)
                        ModelStatusRow(mode: .coreMLBalanced)
                        ModelStatusRow(mode: .coreMLStrict)
                    }
                }
            }
            .padding(16)
        }
        .background(Color.black.ignoresSafeArea())
        .navigationTitle("Diagnostics")
    }

    private func diagnosticRow(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
                .foregroundColor(.gray)
            Spacer()
            Text(value)
                .font(.system(.footnote, design: .monospaced))
                .foregroundColor(.primary)
                .multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
        .padding(10)
        .background(Color.white.opacity(0.055))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct ModelStatusRow: View {
    let mode: RuntimeModelMode

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .foregroundColor(color)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 4) {
                Text(mode.localizedDisplayNameKey)
                    .font(.subheadline.weight(.semibold))
                Text(description)
                    .font(.caption)
                    .foregroundColor(.gray)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()

            Text(badge)
                .font(.caption2.weight(.semibold))
                .foregroundColor(color)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
    }

    private var icon: String {
        mode.isBundled && mode.isProductionReady ? "checkmark.seal.fill" : "exclamationmark.triangle.fill"
    }

    private var color: Color {
        mode.isBundled && mode.isProductionReady ? .green : .orange
    }

    private var badge: String {
        if !mode.isBundled { return "Missing" }
        if mode == .detectorDfine { return "Default" }
        if mode.isProductionReady { return "Installed" }
        return "Needs Training"
    }

    private var description: String {
        switch mode {
        case .coreMLStrict:
            return "Classic scanner with a strict CNN confirmation threshold."
        case .coreMLBalanced:
            return "Classic scanner with faster CNN confirmation."
        case .detectorYolox:
            return "Full-frame detector profile with YOLOX NMS tuning."
        case .detectorDfine:
            return "Recommended full-frame detector and confidence confirmation."
        }
    }
}
