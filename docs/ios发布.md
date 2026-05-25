# iOS App Store 发布计划

> 目标：将 Mosquito Finder 打磨至 App Store 发布标准（国际版，中英文双语）

---

## 一、现状问题汇总

### 1.1 用户体验 (UX)
| 问题 | 现状 | 影响 |
|------|------|------|
| "录像感"交互范式 | 点击"开始狩猎"后进入全屏相机+顶部计时+底部停止按钮，和录像 App 完全一样 | 用户不知道 App 在做什么，误以为在录像 |
| 顶部 HUD 图标无说明 | `S1 / S2 / CAND / TRK / ZOOM / CTR / TRG` 对任何普通用户都是黑箱 | 不可理解 |
| VISION LINK 诊断面板 | 开发者调试信息暴露在生产界面 | 降低专业感，App Store 审核时可能被质疑 |
| "SYSTEM READY" 调试文字 | 左上角半透明绿色文字残留在生产代码 | 明显 debug artifact |
| 阶段名称全为中文 | `准备中 / 搜索中 / 锁定中 / 已发现!` | 国际版用户看不懂 |
| 闪光灯默认开启 | 用户点开始即强制开灯，无提示、无选择 | 体验突兀 |

### 1.2 国际化 (i18n)
- 所有 UI 字符串均硬编码为中文
- 无 `.xcstrings` / `Localizable.strings` 文件
- App 名称、权限申请文字、Alert 提示均为中文

### 1.3 图标与视觉
- AppIcon 占位符（无实际图片文件，Contents.json 有 slot 但无 filename）
- 使用 `ant.circle.fill` SF Symbol 作为 Logo（蚂蚁 ≠ 蚊子，语义错误）
- 缺少启动屏 (LaunchScreen) 配置

### 1.4 App Store 合规
- 缺少隐私权限使用说明（Camera / NSSensorKit）
- 缺少 Privacy Manifest（PrivacyInfo.xcprivacy）— iOS 17+ 必须提交
- Bundle ID 以 `-LP4ALNBL6.` 开头（团队 ID 前缀正常，但 bundle name 需确认）
- 没有 App Store Connect 上的 metadata（截图、描述、关键字）
- CoreML 模型 Validator Warning（不 block 审核，但建议修正）

---

## 二、优化计划

优先级从高到低，按 App Store 卡点风险排序。

---

### P0 — 必须完成，否则无法通过审核

#### T1：修复权限说明文字（国际化+合规）⚡ **Copilot 做**
- 在 `Info.plist` 中添加 `NSCameraUsageDescription`（中英文）
- 可选：`NSMotionUsageDescription`（已使用 CoreMotion）
- 可选：`NSLocationWhenInUseUsageDescription`（未使用，不加）

#### T2：添加 Privacy Manifest ⚡ **Copilot 做**
- 新建 `PrivacyInfo.xcprivacy` 文件（iOS 17+ 合规要求）
- 声明：摄像头使用原因 = `NSPrivacyAccessedAPICategoryCamera`

#### T3：App Icon ⚠️ **需要你提供图片**
- 需要你提供或制作一张 **1024×1024 PNG** App 图标（无 Alpha 通道）
- 我可以先在代码里为图标留好正确的 `Contents.json` slot
- 建议风格：深色背景 + 绿色准星/蚊子图案，契合 App 夜视仪主题
- 📌 **你的操作**：提供图片文件，我来放入正确路径

---

### P1 — 强烈建议，影响用户理解与留存

#### T4：删除调试 UI ⚡ **Copilot 做**
- 移除 `HuntingView` 中 `"SYSTEM READY"` 调试文字
- 将 `VISION LINK` 诊断面板改为仅在 Debug 编译时显示（`#if DEBUG`）

#### T5：重构启动/会话 UX，消除"录像感" ⚡ **Copilot 做**
- 把顶部计时器改为 **目标计数** 样式（"已发现 X 个"），而非纯时间计数器，时间可保留但降级为次要信息
- 底部控制栏改为语义清晰的布局：
  - **手电筒**（图标+文字 Flashlight / 灯光）
  - **对焦**（图标+文字 Focus / 对焦）
  - **结束**（图标+文字 Stop / 结束）—— 原来叫"停止"，改成"结束"语义更自然
  - 保留变焦滑块
- 顶部状态从"搜索中"改为更直观的状态徽章（见 T6）

#### T6：修复 HUD 阶段名称语义 ⚡ **Copilot 做**
- `displayName` 改为 `(英文, 中文)` 双语，按系统语言自动切换
  - idle → "Ready / 就绪"
  - scanning → "Scanning / 扫描中"
  - engaging → "Targeting / 锁定中"
  - killing → "Found! / 发现目标!"

#### T7：国际化（i18n）框架搭建 ⚡ **Copilot 做**
- 新建 `en.lproj/Localizable.strings` 和 `zh-Hans.lproj/Localizable.strings`
- 提取所有硬编码字符串（约 20 个）
- 使用 `NSLocalizedString()` 替换
- 包含：启动页文字、按钮标签、Alert 标题、权限说明文字

关键字符串对照表（设计输出给你参考）：

| Key | English | 中文 |
|-----|---------|------|
| `app.tagline` | Mosquito Finder | 猎蚊者 |
| `start.button` | Start Hunting | 开始狩猎 |
| `stop.button` | End Session | 结束 |
| `flashlight.label` | Light | 灯光 |
| `focus.label` | Focus | 对焦 |
| `found.title` | Mosquito Found! | 发现蚊子！ |
| `found.handled` | Done | 已处理 |
| `phase.ready` | Ready | 就绪 |
| `phase.scanning` | Scanning | 扫描中 |
| `phase.targeting` | Targeting | 锁定中 |
| `phase.found` | Found! | 已发现！ |
| `confidence.label` | Confidence | 置信度 |
| `session.found` | Found: %d | 已发现：%d |
| `hint.flashlight` | Auto flashlight enabled | 🔦 自动开启闪光灯 |
| `hint.scan` | Scan walls for targets | 📍 扫描墙面寻找可疑目标 |
| `hint.zoom` | Zoom in to confirm | 🎯 靠近或变焦确认蚊子 |
| `error.prefix` | Error: | 错误: |
| `permission.camera` | Mosquito Finder uses the camera to detect and track mosquitoes in real time. | 猎蚊者需要使用摄像头实时检测和追踪蚊子。 |

---

### P2 — 优化完善，提升上架质量

#### T8：App Store 截图和文案 ⚠️ **需要你参与**
- App Store 需要至少 3 张截图（6.9" / 6.5" / 5.5"）
- 📌 **你的操作**：用模拟器截图，我可以帮你写 App 的文案（英文 + 中文）
  - 我可以现在就帮你准备好文案草稿

#### T9：LaunchScreen 配置 ⚡ **Copilot 做**
- 检查是否有 `LaunchScreen.storyboard`；如有 Xcode 自动生成的占位符，保留即可
- 若项目使用 `UILaunchScreen` Info.plist key，确认显示 App 名 + 背景色匹配主题

#### T10：CoreML 模型 Validator Warning 修正 ⚡ **Copilot 做**（低优先级）
- 当前 `coremlc` warning：probabilities layer validator warning
- 不阻止编译/运行，但可通过重新生成 spec 清除
- 已修复代码逻辑，可在签名提交前再跑一次确认

---

## 三、分工汇总

| 任务 | 负责方 | 工作量估算 |
|------|--------|-----------|
| T1 权限说明 | Copilot | 5 分钟 |
| T2 Privacy Manifest | Copilot | 5 分钟 |
| T3 App Icon | **你提供图片** | 需要你提供 1024×1024 PNG |
| T4 删除调试 UI | Copilot | 10 分钟 |
| T5 UX 重构（消除录像感） | Copilot | 30 分钟 |
| T6 HUD 阶段名称双语 | Copilot | 10 分钟 |
| T7 国际化框架搭建 | Copilot | 30 分钟 |
| T8 截图 + App Store 文案 | **你截图**，Copilot 写文案 | 文案可立即输出 |
| T9 LaunchScreen | Copilot | 5 分钟 |
| T10 CoreML Warning 清理 | Copilot | 5 分钟 |

---

## 四、发布前自检清单（Apple Review Guidelines）

- [ ] Camera 权限说明文字已填写且说明使用场景
- [ ] Privacy Manifest 包含所有使用到的 API 类型
- [ ] App Icon 1024×1024 无圆角，无 Alpha 通道
- [ ] App 在无网络环境可正常运行（本地模型，符合要求）
- [ ] App 在模拟器 + 真机均 BUILD SUCCEEDED
- [ ] 无 `UIWebView`（已用 SwiftUI）
- [ ] 没有隐藏或伪装的功能
- [ ] App Store 截图与实际功能一致
- [ ] 关键词不包含竞品品牌名
- [ ] 支持至少 iPhone（无 iPad-only）
- [ ] 签名证书 Distribution + Provisioning Profile 有效

---

> 请审阅以上计划，确认无误后回复"开始"，我将依 P0→P1→P2 顺序逐一实施。
> T3（App Icon）和 T8（截图）需要你的资源，其余全部由 Copilot 自动完成。

---

---

# 五、你需要执行的完整发布步骤

> ⚡ 以下是当前可以直接操作的步骤。Copilot 已完成的技术部分：PrivacyInfo.xcprivacy 合规声明、ExportOptions.plist、隐私政策文档。

---

## ⚠️ 发布前必读：两个关键决策

### 问题 A：Bundle ID 以连字符开头（`-LP4ALNBL6.Mosquito-finder`）

Apple 要求 Bundle ID 采用反向域名格式（如 `com.yourname.mosquitofinder`）。当前 ID 以 `-` 开头是 Xcode 自动生成的个人开发团队前缀，**在 App Store Connect 创建 App 时可能被拒绝**。

**建议**：在 App Store Connect 注册前，先在 Xcode 的 Signing & Capabilities 中把 Bundle ID 改为：
```
com.nsaviour.mosquitofinder
```
（或任何你拥有的反向域名格式）改完之后 Xcode 会自动重新匹配 Provisioning Profile。

### 问题 B：最低系统要求 iOS 26.1

当前 Deployment Target 是 iOS 26.1。iOS 26 预计于 2026 年秋季正式发布，**上架后用户必须升级到 iOS 26.1+ 才能下载**，这会显著限制早期用户量。

**建议**：如果 App 没有用到 iOS 26 专属 API，可以在 Xcode 的 Build Settings 中将 `IPHONEOS_DEPLOYMENT_TARGET` 改为 `18.0`，覆盖更广泛的用户。

---

## 第一步：准备 Apple Developer 账号证书

1. 打开 [developer.apple.com/account](https://developer.apple.com/account)
2. 确认你的付费开发者账号（$99/年）处于有效状态
3. 在 Xcode → Settings → Accounts 中登录该 Apple ID
4. 进入 `Xcode → Preferences → Accounts → 选择你的账号 → Manage Certificates`
5. 点击 `+` → 选择 `Apple Distribution` 创建发布证书（如果没有的话）

---

## 第二步：在 App Store Connect 创建 App 记录

1. 打开 [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
2. 点击 `My Apps` → `+` → `New App`
3. 填写：
   - **Platforms**: iOS
   - **Name**: `猎蚊者` （中国区）/ `Mosquito Finder`（其他区）
   - **Primary Language**: Chinese (Simplified)（或 English，取决于你的主要目标市场）
   - **Bundle ID**: 选择你在决策 A 中确认的 Bundle ID（需先在 developer.apple.com Identifiers 中注册）
   - **SKU**: `mosquito-finder-v1`（自定义，内部用）
4. 点击 Create

---

## 第三步：填写 App Store 元数据（直接复制粘贴）

### 3.1 中文（简体）版本

在 App Store Connect → App Information → Localizations → Chinese (Simplified) 填写：

| 字段 | 内容 |
|------|------|
| **名称**（30字符） | `猎蚊者` |
| **副标题**（30字符） | `手机变蚊子雷达，找到它` |
| **宣传文字**（170字符，随时可改） | `睡前再也不用满屋找蚊子。猎蚊者开启手电筒扫墙面，AI 实时标出可疑目标，靠近确认即变红 — 完全离线，不收集任何数据。` |

**描述**（4000字符以内，直接复制）：
```
听到嗡嗡声，就是找不到蚊子？猎蚊者把你的 iPhone 变成一台实时蚊子探测仪。

【工作原理】

🔦 扫描模式
开启后手电筒自动亮起。对着墙面、天花板缓缓扫动，AI 会实时用黄色光圈标出所有"可疑目标"——就像夜视仪，但专门为找蚊子设计。

🎯 确认模式
对准黄色光圈靠近，或将画面放大 1.5× 以上。AI 对中心目标进行二次机器学习分析——若确认是蚊子，光圈变红，手机同步震动反馈，狙击手锁定感十足。

🖥️ 夜视仪界面
绿色薄膜叠加 + 扫描线动效 + 战术准星，提供沉浸式"狩猎"体验。支持中英文切换。

【适用场景】
• 睡前找那只嗡嗡叫的蚊子
• 白墙或阴暗处的蚊子难以肉眼发现
• 需要保持清洁环境的家庭

【技术亮点】
• 两阶段 AI：启发式暗点识别 + CoreML 机器学习分类器
• 防抖机制：检测到手机剧烈晃动时自动暂停，减少误报
• 手电筒自动补光，专为低光环境优化
• 完全离线运行，无任何数据上传

注：检测效果受光照和背景影响。建议在浅色背景（白墙最佳）下、开启手电筒使用，效果最佳。
```

**关键词**（100字符以内，英文逗号分隔，不含空格）：
```
捉蚊,捕虫,找虫,害虫,室内,夏天,驱虫,相机识别,AI检测,夜视仪,暗处,灭蚊,虫子
```

---

### 3.2 英文（美国）版本

在 App Store Connect → Localizations → English (U.S.) 填写：

| 字段 | 内容 |
|------|------|
| **Name**（30 chars） | `Mosquito Finder` |
| **Subtitle**（30 chars） | `Your Personal Mosquito Radar` |
| **Promotional Text**（170 chars） | `No more hunting mosquitoes by ear. Scan walls with AI-powered detection — flashlight on, real-time yellow halos, red lock-on confirmation. 100% offline.` |

**Description**（copy-paste ready）:
```
Hear that buzz but can't find the mosquito? Mosquito Finder turns your iPhone into a real-time mosquito detector.

HOW IT WORKS

🔦 Scan Mode
The flashlight activates automatically. Slowly sweep your phone across walls and ceilings — the AI marks suspicious spots with yellow halos in real time. Think night-vision goggles, designed for mosquito hunting.

🎯 Confirm Mode
Move closer to a yellow halo, or zoom in to 1.5× or more. The AI runs a second-stage machine learning analysis on the centered target. If it's a mosquito — the halo turns red and your phone vibrates. Locked on.

🖥️ Tactical HUD
Subtle green film overlay + animated scan lines + tactical crosshair for an immersive hunting experience. Full English / Chinese bilingual support.

GREAT FOR
• Hunting down that single mosquito before bed
• Finding mosquitoes on white walls or in dark corners
• Anyone who needs a bug-free environment

TECHNICAL HIGHLIGHTS
• Two-stage AI: heuristic dark-spot detection + CoreML classifier
• Motion-aware: auto-pauses during shaky movements to reduce false positives
• Flashlight auto-activates for low-light environments
• 100% offline — no data collection, no uploads, full privacy

Note: Detection accuracy depends on lighting conditions, background color, and distance. Best results on white or light-colored surfaces with flashlight enabled.
```

**Keywords**（under 100 chars）:
```
bug detector,pest control,camera AI,night vision,insect finder,mosquito trap,bedroom,summer
```

---

### 3.3 其他必填字段

| 字段 | 内容 |
|------|------|
| **Support URL** | 你的网站或 GitHub 仓库 URL |
| **Privacy Policy URL** | 见第四步（必须填，否则无法提交） |
| **Age Rating** | 在 App Rating 页面填问卷 → 结果应为 **4+** |
| **Category** | Primary: `Utilities`，Secondary: `Lifestyle` |
| **Price** | 按你的定价策略选择（免费 / 付费） |
| **Availability** | 选择你要发布的国家/地区 |

---

## 第四步：发布隐私政策

App Store 要求**必须**提供一个公开可访问的隐私政策 URL。

**最简单的方式 — GitHub Pages**：
1. 在 GitHub 新建一个公开仓库，例如 `mosquito-finder-privacy`
2. 创建 `README.md`，内容从 `docs/privacy_policy.md` 复制（记得把邮箱替换为你的真实邮箱）
3. 在仓库 Settings → Pages 中开启 GitHub Pages
4. 得到 URL，格式如：`https://yourusername.github.io/mosquito-finder-privacy/`
5. 将此 URL 填入 App Store Connect 的 Privacy Policy URL 字段

---

## 第五步：准备截图

App Store 要求每个语言版本至少 1 张截图，建议 3 张以上。
**必须**有 iPhone 6.7" / 6.9" 尺寸（1320×2868 px 或 1290×2796 px）。

**操作方法**：
1. 在 Xcode 中选择 `iPhone 16 Pro Max` 模拟器
2. 运行 App，用模拟器截图（`Command + S` 或 `Device → Screenshot`）
3. 建议截图内容：
   - 截图 1：启动页（App 名称 + "Start Hunting" 按钮 + 功能说明）
   - 截图 2：扫描中状态，画面有黄色光圈目标框
   - 截图 3：发现蚊子状态（红框 + 底部 "MOSQUITO FOUND" 面板）
4. 可用 Sketch / Figma / Canva 给截图加上简短说明文字再上传

**App Icon**：  
当前 `Assets.xcassets/AppIcon.appiconset/AppIcon.jpg` 已填入一张图，需确认它是 1024×1024 无圆角无 Alpha 通道的 PNG/JPG。

---

## 第六步：Archive 并上传到 App Store Connect

在项目根目录执行：

```bash
cd /Users/nsaviour/Project/AppleProject/Mosquito-finder

# 1. Archive（生成发布包）
xcodebuild archive \
  -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -configuration Release \
  -archivePath build/Mosquito-finder.xcarchive \
  -allowProvisioningUpdates \
  2>&1 | grep -E "error:|warning:|ARCHIVE SUCCEEDED|ARCHIVE FAILED"

# 2. 导出并上传到 App Store Connect
xcodebuild -exportArchive \
  -archivePath build/Mosquito-finder.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export \
  -allowProvisioningUpdates \
  2>&1 | tail -20
```

或者更简单的 **Xcode 图形化方式**：
1. `Product → Archive`（等待完成）
2. 弹出 Organizer 窗口，选中刚刚的 Archive
3. 点击 `Distribute App`
4. 选择 `App Store Connect` → `Upload`
5. 按引导完成，Xcode 会自动处理签名和上传

---

## 第七步：在 App Store Connect 提交审核

1. 打开 App Store Connect → 你的 App → `1.0 Prepare for Submission`
2. 确认以下已填写完整：
   - [ ] 截图（至少 1 张 iPhone 6.7"/6.9"）
   - [ ] 描述、关键词（见第三步文案）
   - [ ] Privacy Policy URL（见第四步）
   - [ ] Support URL
   - [ ] Age Rating 问卷完成
   - [ ] Build 已上传（上传后约 15 分钟出现在 TestFlight / Builds 列表）
3. 在 Build 选择上传的版本
4. 点击 `Submit for Review`

**审核时间**：通常 24 小时 ~ 3 个工作日。首次提交建议选 `Automatically release this version` 以便通过后立即上线。

---

## 发布后检查清单

- [ ] App Store 页面截图显示正常
- [ ] 从 App Store 实际下载测试（非 TestFlight）
- [ ] 测试相机权限申请弹框文字正确显示
- [ ] 测试运动权限申请弹框（第一次靠近检测时触发）
- [ ] App 在无 Wi-Fi 环境下正常运行（预期行为）

