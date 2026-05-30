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

// 模拟战绩页
struct TrophyView: View {
    var body: some View {
        NavigationView {
            List {
                Section(header: Text("Hunting History")) {
                    Text("No records yet. Start hunting!")
                        .foregroundColor(.gray)
                        .padding(.vertical, 20)
                }
            }
            .navigationTitle("Trophies")
        }
    }
}

// 模拟设置页
struct SettingsView: View {
    @AppStorage("enableHaptics") private var enableHaptics = true
    @AppStorage("radarSensitivity") private var radarSensitivity = 0.5
    @AppStorage("autoFlashlight") private var autoFlashlight = true
    @AppStorage("appLanguage") private var appLanguage: String = ""
    @AppStorage("detectionModelMode") private var detectionModelMode = RuntimeModelMode.coreMLStrict.rawValue
    @AppStorage("stage2ConfidenceThreshold") private var stage2ConfidenceThreshold = Double(RuntimeDetectionSettings.strict.stage2ConfidenceThreshold)
    @AppStorage("minZoomFactor") private var minZoomFactor = Double(RuntimeDetectionSettings.strict.minZoomFactor)
    @AppStorage("centerRegionRatio") private var centerRegionRatio = Double(RuntimeDetectionSettings.strict.centerRegionRatio)
    @AppStorage("minTargetSize") private var minTargetSize = Double(RuntimeDetectionSettings.strict.minTargetSize)
    @AppStorage("stableFrameCount") private var stableFrameCount = RuntimeDetectionSettings.strict.stableFrameCount
    @AppStorage("maxStage1Detections") private var maxStage1Detections = RuntimeDetectionSettings.strict.maxStage1Detections
    @AppStorage("stage1LocalContrastThreshold") private var stage1LocalContrastThreshold = Double(RuntimeDetectionSettings.strict.stage1LocalContrastThreshold)

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Model")) {
                    Picker("Runtime Model", selection: $detectionModelMode) {
                        ForEach(RuntimeModelMode.allCases) { mode in
                            Text(mode.displayName).tag(mode.rawValue)
                        }
                    }

                    if selectedModelMode.isDetectorMode {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Detector model placeholder")
                                .font(.footnote)
                                .foregroundColor(.orange)
                            Text("Add DfineMosquitoDetector.mlmodel or YoloxMosquitoDetector.mlmodel to the Xcode target before testing this mode.")
                                .font(.caption)
                                .foregroundColor(.gray)
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
}
