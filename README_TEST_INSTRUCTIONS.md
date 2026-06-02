# Mosquito Finder 本地测试说明

这份说明用于真机录屏验收。当前推荐链路是 `D-FINE Detector`，不要再使用早期“手画黑点作弊测试”的说明。

## 1. 拉取和运行

```bash
cd /Users/nsaviour/Desktop/workplace/codeProject/Mosquito-finder
git pull origin main
open Mosquito-finder.xcodeproj
```

在 Xcode 中选择你的 iPhone，确认 `Signing & Capabilities` 使用自己的开发者账号，然后 `Cmd + R` 运行。

如果你之前装过旧版本，建议先在 iPhone 上删除旧 App，再重新运行，避免旧的本地参数残留。

## 2. 推荐模型和参数

进入 App 的 `Settings`，选择：

- `Runtime Model`: `D-FINE Detector`
- 点击 `D-FINE Detector Preset`
- `Stage 2 Confidence`: `0.50`
- `Min Zoom`: `1.0x`
- `Center Region`: `0.50`
- `Min Target Size`: `8px`
- `Stable Frames`: `2`
- `Stage 1 Max Candidates`: `8`
- `Stage 1 Contrast`: `0.06`

代码会在首次进入 D-FINE 模式时自动写入这组参数；手动检查一遍即可。

## 3. 录屏用测试图片

优先使用当前 D-FINE 训练/验证集中置信度最高的正样本。把图片在 Mac 屏幕上打开，iPhone 摄像头正对屏幕拍摄。

推荐顺序：

1. `data/detector/generated_dfine/reality2017/reality2017_00237.jpg`
2. `data/detector/generated_dfine/reality2017/reality2017_00363.jpg`
3. `data/detector/generated_dfine/reality2017/reality2017_00525.jpg`
4. `data/detector/generated_dfine/val2017/val2017_00182.jpg`
5. `data/detector/generated_dfine/val2017/val2017_00163.jpg`

离线 CoreML 验证分数：

- `reality2017_00237.jpg`: `0.9067`
- `reality2017_00363.jpg`: `0.8984`
- `reality2017_00525.jpg`: `0.8955`
- `val2017_00182.jpg`: `0.9014`
- `val2017_00163.jpg`: `0.8989`

## 4. 拍摄方式

- 图片尽量充满取景画面，但不要糊焦。
- iPhone 正对屏幕，不要斜拍。
- 关闭屏幕反光，避免强摩尔纹。
- 保持 1-2 秒稳定，不要快速扫动。
- 不需要手动画黑点，当前模型不是按纯黑点测试优化的。

如果仍然没有触发，先到 `Settings` 再点一次 `D-FINE Detector Preset`，然后退出 App 重进。
