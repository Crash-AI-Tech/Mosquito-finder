# iOS App Store 发布计划 — Mosquito Finder

> 最后更新：2026-05-26

---

## 状态总览

| # | 任务 | 状态 | 负责方 |
|---|------|------|--------|
| T1 | 权限说明文字（Camera / Motion） | ✅ 已完成 | — |
| T2 | Privacy Manifest（PrivacyInfo.xcprivacy） | ✅ 已完成 | — |
| T3 | App Icon（1024×1024） | ✅ 已有图片（需确认规格） | — |
| T4 | 删除调试 UI（VISION LINK / SYSTEM READY） | ✅ 已完成（代码中已无调用） | — |
| T5 | 消除"录像感"UX（目标计数、按钮文字） | ✅ 已完成 | — |
| T6 | HUD 阶段名称英中双语 | ✅ 已完成（Light / Focus / End 等） | — |
| T7 | App Store 完整文案（中英双语） | ✅ 已完成（见第三节） | — |
| T8 | 官网 + Privacy Policy + Support 页面 | ✅ 已完成（docs/ 目录，已推送 GitHub） | — |
| T9 | ExportOptions.plist | ✅ 已完成 | — |
| — | **开启 GitHub Pages（公开仓库）** | ⏳ **待你操作** | 你 |
| — | **Bundle ID 修改** | ⏳ **待你操作** | 你 |
| — | **截图准备（3 张）** | ⏳ **待你操作** | 你 |
| — | **Archive 并上传** | ⏳ **待你操作** | 你 |
| — | **App Store Connect 填写 + 提审** | ⏳ **待你操作** | 你 |

---

## ⚠️ 两个关键决策（操作前必读）

### 决策 A：修改 Bundle ID（强烈建议）

当前 Bundle ID：`-LP4ALNBL6.Mosquito-finder`（以连字符开头）

Apple 要求反向域名格式，创建 App Store Connect 记录时此 ID 可能被拒。

**操作**：Xcode → 点击项目根节点 → Targets → Signing & Capabilities → Bundle Identifier 改为：
```
com.nsaviour.mosquitofinder
```
保存后 Xcode 会自动重新匹配 Provisioning Profile。

### 决策 B：最低系统版本（建议降低）

当前 `IPHONEOS_DEPLOYMENT_TARGET = 26.1`（iOS 26 秋季才正式发布）

用户必须升级到 iOS 26.1+ 才能下载，早期用户量极少。

**操作**：Xcode → Build Settings → 搜索 `iOS Deployment Target` → 改为 `18.0`（适用范围最广）

---

## 你需要按顺序执行的步骤

---

### 第一步：开启 GitHub Pages（获取 Privacy Policy 和 Support URL）

**1.1 把仓库设为 Public**
- 打开 [github.com/Crash-AI-Tech/Mosquito-finder/settings](https://github.com/Crash-AI-Tech/Mosquito-finder/settings)
- 滚到最底部 → **Danger Zone** → **Change repository visibility** → Make public

**1.2 开启 Pages**
- 进入 **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: `main` / Folder: `/docs`
- 点击 **Save**

**1.3 等待 ~60 秒，获取你的 URL**

| 用途 | URL |
|------|-----|
| 主页 | `https://crash-ai-tech.github.io/Mosquito-finder/` |
| **Privacy Policy URL**（App Store 必填） | `https://crash-ai-tech.github.io/Mosquito-finder/privacy.html` |
| **Support URL**（App Store 必填） | `https://crash-ai-tech.github.io/Mosquito-finder/support.html` |

**1.4 替换邮箱**
打开以下三个文件，把 `your-email@example.com` 改为你的真实邮箱，然后 `git add . && git commit -m "update email" && git push Mosquito-finder main`：
- `docs/privacy.html`
- `docs/support.html`
- `docs/index.html`（Contact 链接处）

---

### 第二步：确认 App Icon

检查 `Mosquito-finder/Assets.xcassets/AppIcon.appiconset/AppIcon.jpg`：
- 尺寸必须是 **1024 × 1024 px**
- **无 Alpha 通道**（PNG/JPG 均可，JPG 天然无 Alpha）
- **无圆角**（Apple 会自动裁圆角）

如果图片是 PNG 含 Alpha：用"预览" App 打开 → 导出 → 去掉"Alpha 通道"勾选 → 存为 JPG。

---

### 第三步：在 Xcode 中改完两个决策 A/B

见上方决策 A（Bundle ID）和决策 B（Deployment Target）。

---

### 第四步：准备截图

截图规格：**iPhone 16 Pro Max 模拟器**（6.9"，1320×2868）

1. Xcode → 选模拟器 `iPhone 16 Pro Max`
2. `Product → Run`，在模拟器里操作到对应状态
3. 模拟器菜单 `File → Save Screenshot`（或 `⌘S`）

建议截图（至少提交 3 张）：
- **截图 1**：启动页（App 名 + Start Hunting 按钮）
- **截图 2**：扫描中，画面有黄色目标框
- **截图 3**：发现蚊子，红框 + "MOSQUITO FOUND" 底部面板

---

### 第五步：Archive 并上传

**推荐方式（Xcode 图形化）**：
1. 菜单 `Product → Archive`（确保 Scheme 选的是真机，不是模拟器）
2. 弹出 Organizer → 选中刚生成的 Archive → 点 **Distribute App**
3. 选 **App Store Connect** → **Upload** → 一路 Next
4. Xcode 自动处理签名，上传完成后在 App Store Connect 的 TestFlight/Builds 约 15 分钟后出现

**命令行方式（可选）**：
```bash
cd /Users/nsaviour/Project/AppleProject/Mosquito-finder

xcodebuild archive \
  -project Mosquito-finder.xcodeproj \
  -scheme Mosquito-finder \
  -configuration Release \
  -archivePath build/Mosquito-finder.xcarchive \
  -allowProvisioningUpdates \
  2>&1 | grep -E "error:|ARCHIVE SUCCEEDED|ARCHIVE FAILED"

xcodebuild -exportArchive \
  -archivePath build/Mosquito-finder.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export \
  -allowProvisioningUpdates \
  2>&1 | tail -10
```

---

### 第六步：在 App Store Connect 创建 App 并填写信息

**6.1 创建 App 记录**
1. 打开 [appstoreconnect.apple.com](https://appstoreconnect.apple.com) → My Apps → `+` → New App
2. Platforms: `iOS`，Name: `Mosquito Finder`，Primary Language: `English`
3. Bundle ID: 选择你在第三步改好的 ID
4. SKU: `mosquito-finder-v1`，点 Create

**6.2 填写英文版**（English (U.S.)）

| 字段 | 内容 |
|------|------|
| Name | `Mosquito Finder` |
| Subtitle | `Your Personal Mosquito Radar` |
| Promotional Text | `No more hunting mosquitoes by ear. Scan walls with AI-powered detection — flashlight on, real-time yellow halos, red lock-on confirmation. 100% offline.` |
| Keywords | `bug detector,pest control,camera AI,night vision,insect finder,mosquito trap,bedroom,summer` |

Description（复制粘贴）：
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

Note: Detection accuracy depends on lighting and background. Best results on white or light-colored surfaces with flashlight enabled.
```

**6.3 添加中文版**（Chinese (Simplified)）

| 字段 | 内容 |
|------|------|
| 名称 | `猎蚊者` |
| 副标题 | `手机变蚊子雷达，找到它` |
| 宣传文字 | `睡前再也不用满屋找蚊子。猎蚊者开启手电筒扫墙面，AI 实时标出可疑目标，靠近确认即变红 — 完全离线，不收集任何数据。` |
| 关键词 | `捉蚊,捕虫,找虫,害虫,室内,夏天,驱虫,相机识别,AI检测,夜视仪,暗处,灭蚊,虫子` |

Description（复制粘贴）：
```
听到嗡嗡声，就是找不到蚊子？猎蚊者把你的 iPhone 变成一台实时蚊子探测仪。

【工作原理】

🔦 扫描模式
开启后手电筒自动亮起。对着墙面、天花板缓缓扫动，AI 会实时用黄色光圈标出所有"可疑目标"——就像夜视仪，但专门为找蚊子设计。

🎯 确认模式
对准黄色光圈靠近，或将画面放大 1.5× 以上。AI 对中心目标进行二次机器学习分析——若确认是蚊子，光圈变红，手机同步震动反馈。

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

**6.4 填写其他必填项**

| 字段 | 内容 |
|------|------|
| Privacy Policy URL | `https://crash-ai-tech.github.io/Mosquito-finder/privacy.html` |
| Support URL | `https://crash-ai-tech.github.io/Mosquito-finder/support.html` |
| Category | Primary: **Utilities**，Secondary: **Lifestyle** |
| Age Rating | 填问卷 → 结果为 **4+** |
| Price | 按你的定价选择 |

---

### 第七步：选择 Build 并提交审核

1. App Store Connect → 你的 App → `1.0 Prepare for Submission`
2. 在 Build 区域选择第五步上传的版本
3. 上传截图（至少 1 张 6.9" iPhone）
4. 确认所有字段已填绿色勾 ✓
5. 点击 **Submit for Review**
6. 审核通知方式：选 `Automatically release this version`（通过即上线）

审核时间：通常 24 小时内，最长 3 个工作日。

---

## 发布后核查

- [ ] App Store 页面公开可访问
- [ ] 从 App Store 下载测试（非 TestFlight）
- [ ] 相机权限弹框文字正确
- [ ] App 无网络下正常运行
- [ ] `docs/index.html` 中的 App Store 下载链接换成真实 URL，重新 push
