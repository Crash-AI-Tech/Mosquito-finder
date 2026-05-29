import SwiftUI

struct MainTabView: View {
    @State private var selectedTab = 0
    
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

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Detection Settings")) {
                    Toggle("Auto Flashlight", isOn: $autoFlashlight)
                    VStack(alignment: .leading) {
                        Text("Radar Sensitivity")
                        Slider(value: $radarSensitivity, in: 0...1)
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
}
