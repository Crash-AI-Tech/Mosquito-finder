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
