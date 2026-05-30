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
    @AppStorage("radarSensitivity") private var radarSensitivity = 0.5
    @AppStorage("autoFlashlight") private var autoFlashlight = true
    @AppStorage("appLanguage") private var appLanguage: String = ""
    @AppStorage("detectionModelMode") private var detectionModelMode = RuntimeModelMode.preferredDefault.rawValue
    @AppStorage("stage2ConfidenceThreshold") private var stage2ConfidenceThreshold = Double(RuntimeDetectionSettings.current.stage2ConfidenceThreshold)
    @AppStorage("minZoomFactor") private var minZoomFactor = Double(RuntimeDetectionSettings.current.minZoomFactor)
    @AppStorage("centerRegionRatio") private var centerRegionRatio = Double(RuntimeDetectionSettings.current.centerRegionRatio)
    @AppStorage("minTargetSize") private var minTargetSize = Double(RuntimeDetectionSettings.current.minTargetSize)
    @AppStorage("stableFrameCount") private var stableFrameCount = RuntimeDetectionSettings.current.stableFrameCount
    @AppStorage("maxStage1Detections") private var maxStage1Detections = RuntimeDetectionSettings.current.maxStage1Detections
    @AppStorage("stage1LocalContrastThreshold") private var stage1LocalContrastThreshold = Double(RuntimeDetectionSettings.current.stage1LocalContrastThreshold)

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Model")) {
                    Picker("Runtime Model", selection: $detectionModelMode) {
                        ForEach(RuntimeModelMode.selectableCases) { mode in
                            Text(mode.localizedDisplayNameKey).tag(mode.rawValue)
                        }
                    }

                    HStack {
                        Button("Strict Preset") {
                            applyPreset(.coreMLStrict)
                        }
                        Spacer()
                        Button("Balanced Preset") {
                            applyPreset(.coreMLBalanced)
                        }
                    }

                    if RuntimeModelMode.detectorYolox.isBundled {
                        Button("YOLOX High Precision Preset") {
                            applyPreset(.detectorYolox)
                        }
                    }
                }

                Section(header: Text("Model Availability")) {
                    modelStatusRow(.coreMLStrict)
                    modelStatusRow(.coreMLBalanced)
                    modelStatusRow(.detectorYolox)
                    modelStatusRow(.detectorDfine)
                }

                Section(header: Text("Detection Settings")) {
                    Toggle("Auto Flashlight", isOn: $autoFlashlight)
                    settingSlider(
                        title: "Stage 2 Confidence",
                        value: $stage2ConfidenceThreshold,
                        range: 0.50...0.99,
                        format: "%.2f"
                    )
                    settingSlider(
                        title: "Min Zoom",
                        value: $minZoomFactor,
                        range: 1.0...5.0,
                        format: "%.1fx"
                    )
                    settingSlider(
                        title: "Center Region",
                        value: $centerRegionRatio,
                        range: 0.15...0.45,
                        format: "%.2f"
                    )
                    settingSlider(
                        title: "Min Target Size",
                        value: $minTargetSize,
                        range: 10...60,
                        format: "%.0fpx"
                    )
                    Stepper("Stable Frames: \(stableFrameCount)", value: $stableFrameCount, in: 2...12)
                    Stepper("Stage 1 Max Candidates: \(maxStage1Detections)", value: $maxStage1Detections, in: 1...12)
                    settingSlider(
                        title: "Stage 1 Contrast",
                        value: $stage1LocalContrastThreshold,
                        range: 0.04...0.16,
                        format: "%.2f"
                    )
                }

                Section(header: Text("Language")) {
                    Picker("App Language", selection: $appLanguage) {
                        Text("Follow System").tag("")
                        Text("English").tag("en")
                        Text("Simplified Chinese").tag("zh-Hans")
                    }
                }
                
                Section(header: Text("Feedback")) {
                    Toggle("Haptic Feedback", isOn: $enableHaptics)
                }
                
                Section(header: Text("About")) {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.0.0").foregroundColor(.gray)
                    }
                }
            }
            .navigationTitle("Settings")
            .onAppear {
                if !selectedModelMode.isBundled || !selectedModelMode.isProductionReady {
                    applyPreset(RuntimeModelMode.preferredDefault)
                }
            }
        }
    }

    private var selectedModelMode: RuntimeModelMode {
        RuntimeModelMode(rawValue: detectionModelMode) ?? .coreMLStrict
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
        maxStage1Detections = settings.maxStage1Detections
        stage1LocalContrastThreshold = Double(settings.stage1LocalContrastThreshold)
    }

    private func settingSlider(
        title: LocalizedStringKey,
        value: Binding<Double>,
        range: ClosedRange<Double>,
        format: String
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(title)
                Spacer()
                Text(String(format: format, value.wrappedValue))
                    .foregroundColor(.gray)
                    .font(.system(.footnote, design: .monospaced))
            }
            Slider(value: value, in: range)
        }
    }

    private func modelStatusRow(_ mode: RuntimeModelMode) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: modelStatusIcon(mode))
                .foregroundColor(modelStatusColor(mode))
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 4) {
                Text(mode.localizedDisplayNameKey)
                Text(modelStatusDescription(mode))
                    .font(.caption)
                    .foregroundColor(.gray)
            }
            Spacer()
            Text(modelStatusBadge(mode))
                .font(.caption2.weight(.semibold))
                .foregroundColor(modelStatusColor(mode))
        }
    }

    private func modelStatusIcon(_ mode: RuntimeModelMode) -> String {
        mode.isBundled && mode.isProductionReady ? "checkmark.seal.fill" : "exclamationmark.triangle.fill"
    }

    private func modelStatusColor(_ mode: RuntimeModelMode) -> Color {
        mode.isBundled && mode.isProductionReady ? .green : .orange
    }

    private func modelStatusBadge(_ mode: RuntimeModelMode) -> LocalizedStringKey {
        if !mode.isBundled { return "Not installed" }
        if mode == .detectorYolox { return "Recommended" }
        if mode.isProductionReady { return "Installed" }
        return "Needs training"
    }

    private func modelStatusDescription(_ mode: RuntimeModelMode) -> LocalizedStringKey {
        switch mode {
        case .coreMLStrict:
            return "Strict CoreML mode minimizes false positives."
        case .coreMLBalanced:
            return "Balanced CoreML mode is faster to confirm targets."
        case .detectorYolox:
            return "YOLOX detector is bundled and uses the best current mosquito detector."
        case .detectorDfine:
            return "D-FINE is kept as a research path and is not enabled until accuracy improves."
        }
    }
}
