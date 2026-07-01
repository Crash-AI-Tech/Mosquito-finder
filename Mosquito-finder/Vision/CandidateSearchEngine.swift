//
//  CandidateSearchEngine.swift
//  Mosquito-finder
//
//  Stage 1 candidate search. This stage does not decide "mosquito".
//  It proposes areas worth moving closer to and lets Stage 2 make the call.
//

import Foundation
import Combine
import CoreGraphics
import CoreVideo

final class CandidateSearchEngine: ObservableObject {

    @Published var isProcessing = false
    @Published var lastProcessingTime: TimeInterval = 0
    @Published var candidateCount: Int = 0

    var modelMode: RuntimeModelMode = .classic
    var maxCandidates: Int = 8
    var frameInterval: TimeInterval = 0.12
    var localContrastThreshold: Float = 0.06
    var backgroundVarianceThreshold: Float = 0.018
    var detectorCandidateThreshold: Float = 0.18
    var detectorNmsIouThreshold: CGFloat = 0.35
    var candidateClassifierEnabled = true
    var candidateClassifierWeight: Float = 0.26

    private let modelScanner = Stage1Detector()
    private let candidateClassifier = CandidateClassifier()
    private var lastFrameTime: Date?
    private var isBusy = false
    private var tracks: [CandidateTrack] = []
    private let maxTrackMisses = 4
    private var previousMotionGrid: MotionGrid?
    private let motionCellSize = 16

    func search(pixelBuffer: CVPixelBuffer) -> [SuspectRegion] {
        let now = Date()
        if let lastFrameTime, now.timeIntervalSince(lastFrameTime) < frameInterval {
            return []
        }
        if isBusy { return [] }

        isBusy = true
        lastFrameTime = now
        let started = now
        DispatchQueue.main.async { self.isProcessing = true }

        var output: [SuspectRegion] = []
        defer {
            let duration = Date().timeIntervalSince(started)
            let count = output.count
            DispatchQueue.main.async {
                self.isProcessing = false
                self.lastProcessingTime = duration
                self.candidateCount = count
            }
            isBusy = false
        }

        configureModelScanner()
        let modelCandidates = modelScanner.detectDarkSpots(pixelBuffer: pixelBuffer)
        let traditionalCandidates = findTraditionalCandidates(pixelBuffer: pixelBuffer)
        let rawCandidates = nonMaximumSuppressed(
            modelCandidates + traditionalCandidates,
            iouThreshold: 0.28
        )
        let scoredCandidates = scoreWithCandidateClassifier(rawCandidates, in: pixelBuffer)
        output = stabilize(scoredCandidates)
        return Array(output.prefix(maxCandidates))
    }

    private func configureModelScanner() {
        modelScanner.modelMode = modelMode
        modelScanner.maxDetections = maxCandidates
        modelScanner.frameInterval = 0
        modelScanner.localContrastThreshold = localContrastThreshold
        modelScanner.backgroundVarianceThreshold = backgroundVarianceThreshold
        modelScanner.detectorCandidateThreshold = detectorCandidateThreshold
        modelScanner.detectorNmsIouThreshold = detectorNmsIouThreshold
    }

    private func findTraditionalCandidates(pixelBuffer: CVPixelBuffer) -> [SuspectRegion] {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        guard width > 96, height > 96 else { return [] }

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return [] }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        let buffer = baseAddress.assumingMemoryBound(to: UInt8.self)
        let frameStats = sampleFrameStats(buffer: buffer, bytesPerRow: bytesPerRow, width: width, height: height)
        let adaptiveContrastThreshold = adaptiveLocalContrastThreshold(frameStats: frameStats)
        let adaptiveVarianceThreshold = adaptiveBackgroundVarianceThreshold(frameStats: frameStats)
        let motionCandidates = findMotionCandidates(
            buffer: buffer,
            bytesPerRow: bytesPerRow,
            width: width,
            height: height,
            frameStats: frameStats
        )
        let step = 18
        let margin = 36
        var candidates: [SuspectRegion] = []

        for y in stride(from: margin, to: height - margin, by: step) {
            for x in stride(from: margin, to: width - margin, by: step) {
                let inner = sampleStats(
                    buffer: buffer,
                    bytesPerRow: bytesPerRow,
                    centerX: x,
                    centerY: y,
                    radius: 3
                )
                let middle = sampleStats(
                    buffer: buffer,
                    bytesPerRow: bytesPerRow,
                    centerX: x,
                    centerY: y,
                    radius: 9
                )
                let outer = sampleRingStats(
                    buffer: buffer,
                    bytesPerRow: bytesPerRow,
                    centerX: x,
                    centerY: y,
                    innerRadius: 12,
                    outerRadius: 22
                )

                let darkContrast = outer.mean - inner.mean
                let blobContrast = middle.mean - inner.mean
                let texturePenalty = min(1.0, outer.variance / max(0.0001, backgroundVarianceThreshold * 6))
                let smoothness = 1.0 - texturePenalty

                if darkContrast > adaptiveContrastThreshold {
                    let score = min(1.0, darkContrast * 3.1 + smoothness * 0.22)
                    candidates.append(makeCandidate(x: x, y: y, size: 22, score: score, source: .darkSpot))
                }

                if blobContrast > adaptiveContrastThreshold * 0.78 && outer.variance < adaptiveVarianceThreshold * 10 {
                    let score = min(1.0, blobContrast * 2.7 + smoothness * 0.18)
                    candidates.append(makeCandidate(x: x, y: y, size: 28, score: score, source: .blob))
                }

                let localContrast = sqrt(max(0, middle.variance))
                if localContrast > adaptiveContrastThreshold * 0.68 && darkContrast > adaptiveContrastThreshold * 0.42 {
                    let score = min(1.0, localContrast * 2.2 + darkContrast * 1.5)
                    candidates.append(makeCandidate(x: x, y: y, size: 32, score: score, source: .localContrast))
                }
            }
        }

        candidates.append(contentsOf: findConnectedDarkComponents(
            buffer: buffer,
            bytesPerRow: bytesPerRow,
            width: width,
            height: height,
            frameStats: frameStats,
            contrastThreshold: adaptiveContrastThreshold,
            varianceThreshold: adaptiveVarianceThreshold
        ))
        candidates.append(contentsOf: motionCandidates)

        return nonMaximumSuppressed(
            spatiallyDiverse(candidates.sorted { rankedScore($0) > rankedScore($1) }, imageSize: CGSize(width: width, height: height)),
            iouThreshold: 0.22
        )
        .prefix(maxCandidates * 3)
        .map { $0 }
    }

    private func scoreWithCandidateClassifier(_ candidates: [SuspectRegion], in pixelBuffer: CVPixelBuffer) -> [SuspectRegion] {
        guard candidateClassifierEnabled, !candidates.isEmpty else { return candidates }

        let limited = candidates
            .sorted { rankedScore($0) > rankedScore($1) }
            .prefix(max(maxCandidates * 2, maxCandidates + 4))

        return limited.map { candidate in
            guard let modelScore = candidateClassifier.score(region: expandedClassifierRegion(candidate.boundingBox), in: pixelBuffer) else {
                return candidate
            }

            var updated = candidate
            // Do not hard-filter. Offline candidate-crop eval shows high thresholds
            // lose too much recall, so this model only reranks heuristic proposals.
            let blended = candidate.confidence * (1 - candidateClassifierWeight) + modelScore * candidateClassifierWeight
            let lowSupportPenalty: Float = modelScore < 0.05 ? 0.86 : 1.0
            updated.confidence = max(0.03, min(1, blended * lowSupportPenalty))
            return updated
        }
    }

    private func findConnectedDarkComponents(
        buffer: UnsafePointer<UInt8>,
        bytesPerRow: Int,
        width: Int,
        height: Int,
        frameStats: BrightnessStats,
        contrastThreshold: Float,
        varianceThreshold: Float
    ) -> [SuspectRegion] {
        let cellSize = 12
        let gridWidth = max(1, width / cellSize)
        let gridHeight = max(1, height / cellSize)
        let marginCells = max(2, 36 / cellSize)
        var mask = Array(repeating: false, count: gridWidth * gridHeight)
        var contrast = Array(repeating: Float(0), count: gridWidth * gridHeight)

        for gy in marginCells..<(gridHeight - marginCells) {
            for gx in marginCells..<(gridWidth - marginCells) {
                let x = gx * cellSize + cellSize / 2
                let y = gy * cellSize + cellSize / 2
                let center = sampleStats(buffer: buffer, bytesPerRow: bytesPerRow, centerX: x, centerY: y, radius: 2)
                let ring = sampleRingStats(buffer: buffer, bytesPerRow: bytesPerRow, centerX: x, centerY: y, innerRadius: 10, outerRadius: 20)
                let localContrast = ring.mean - center.mean
                let darkEnough = center.mean < max(0.62, frameStats.mean + 0.08)
                let compactSignal = localContrast > max(0.018, contrastThreshold * 0.48)
                let textureOK = ring.variance < max(0.035, varianceThreshold * 14)
                if darkEnough && compactSignal && textureOK {
                    let index = gy * gridWidth + gx
                    mask[index] = true
                    contrast[index] = localContrast
                }
            }
        }

        var visited = Array(repeating: false, count: mask.count)
        var components: [SuspectRegion] = []
        let maxComponentCells = 26

        for gy in marginCells..<(gridHeight - marginCells) {
            for gx in marginCells..<(gridWidth - marginCells) {
                let start = gy * gridWidth + gx
                if visited[start] || !mask[start] { continue }

                var stack = [(gx, gy)]
                var cells: [(Int, Int)] = []
                var contrastSum: Float = 0
                visited[start] = true

                while let (cx, cy) = stack.popLast() {
                    let index = cy * gridWidth + cx
                    cells.append((cx, cy))
                    contrastSum += contrast[index]

                    for ny in max(marginCells, cy - 1)...min(gridHeight - marginCells - 1, cy + 1) {
                        for nx in max(marginCells, cx - 1)...min(gridWidth - marginCells - 1, cx + 1) {
                            let neighbor = ny * gridWidth + nx
                            if !visited[neighbor], mask[neighbor] {
                                visited[neighbor] = true
                                stack.append((nx, ny))
                            }
                        }
                    }
                }

                guard !cells.isEmpty, cells.count <= maxComponentCells else { continue }
                let minX = cells.map { $0.0 }.min() ?? gx
                let maxX = cells.map { $0.0 }.max() ?? gx
                let minY = cells.map { $0.1 }.min() ?? gy
                let maxY = cells.map { $0.1 }.max() ?? gy
                let componentWidth = CGFloat(maxX - minX + 1) * CGFloat(cellSize)
                let componentHeight = CGFloat(maxY - minY + 1) * CGFloat(cellSize)
                let maxSide = max(componentWidth, componentHeight)
                guard maxSide <= 96 else { continue }

                let centerX = CGFloat(minX + maxX + 1) * CGFloat(cellSize) / 2
                let centerY = CGFloat(minY + maxY + 1) * CGFloat(cellSize) / 2
                let avgContrast = contrastSum / Float(cells.count)
                let compactness = Float(min(1, CGFloat(cells.count) / 8.0))
                let score = min(1, avgContrast * 3.4 + compactness * 0.18)
                let side = max(maxSide + 18, 24)
                components.append(SuspectRegion(
                    boundingBox: CGRect(x: centerX - side / 2, y: centerY - side / 2, width: side, height: side),
                    confidence: max(0.05, score * CandidateSource.blob.weight),
                    source: .blob
                ))
            }
        }

        return components
    }

    private func findMotionCandidates(
        buffer: UnsafePointer<UInt8>,
        bytesPerRow: Int,
        width: Int,
        height: Int,
        frameStats: BrightnessStats
    ) -> [SuspectRegion] {
        let gridWidth = max(1, width / motionCellSize)
        let gridHeight = max(1, height / motionCellSize)
        var values = Array(repeating: Float(0), count: gridWidth * gridHeight)

        for gy in 0..<gridHeight {
            for gx in 0..<gridWidth {
                let x = min(width - 1, gx * motionCellSize + motionCellSize / 2)
                let y = min(height - 1, gy * motionCellSize + motionCellSize / 2)
                values[gy * gridWidth + gx] = brightness(buffer: buffer, bytesPerRow: bytesPerRow, x: x, y: y)
            }
        }

        defer {
            previousMotionGrid = MotionGrid(width: gridWidth, height: gridHeight, values: values)
        }

        guard let previousMotionGrid,
              previousMotionGrid.width == gridWidth,
              previousMotionGrid.height == gridHeight else {
            return []
        }

        let diffs = zip(values, previousMotionGrid.values).map { abs($0 - $1) }
        let meanDiff = diffs.reduce(0, +) / Float(max(1, diffs.count))
        guard meanDiff > 0.004, meanDiff < 0.055 else { return [] }

        let threshold = max(0.045, meanDiff * 3.4)
        var mask = Array(repeating: false, count: values.count)
        let marginCells = max(2, 36 / motionCellSize)
        for gy in marginCells..<(gridHeight - marginCells) {
            for gx in marginCells..<(gridWidth - marginCells) {
                let index = gy * gridWidth + gx
                let changed = diffs[index] > threshold
                let locallyDark = values[index] < max(0.58, frameStats.mean + 0.06)
                if changed && locallyDark {
                    mask[index] = true
                }
            }
        }

        return connectedMotionRegions(
            mask: mask,
            diffs: diffs,
            gridWidth: gridWidth,
            gridHeight: gridHeight,
            cellSize: motionCellSize,
            marginCells: marginCells
        )
    }

    private func connectedMotionRegions(
        mask: [Bool],
        diffs: [Float],
        gridWidth: Int,
        gridHeight: Int,
        cellSize: Int,
        marginCells: Int
    ) -> [SuspectRegion] {
        var visited = Array(repeating: false, count: mask.count)
        var regions: [SuspectRegion] = []

        for gy in marginCells..<(gridHeight - marginCells) {
            for gx in marginCells..<(gridWidth - marginCells) {
                let start = gy * gridWidth + gx
                if visited[start] || !mask[start] { continue }

                var stack = [(gx, gy)]
                var cells: [(Int, Int)] = []
                var diffSum: Float = 0
                visited[start] = true

                while let (cx, cy) = stack.popLast() {
                    let index = cy * gridWidth + cx
                    cells.append((cx, cy))
                    diffSum += diffs[index]
                    for ny in max(marginCells, cy - 1)...min(gridHeight - marginCells - 1, cy + 1) {
                        for nx in max(marginCells, cx - 1)...min(gridWidth - marginCells - 1, cx + 1) {
                            let neighbor = ny * gridWidth + nx
                            if !visited[neighbor], mask[neighbor] {
                                visited[neighbor] = true
                                stack.append((nx, ny))
                            }
                        }
                    }
                }

                guard (1...18).contains(cells.count) else { continue }
                let minX = cells.map { $0.0 }.min() ?? gx
                let maxX = cells.map { $0.0 }.max() ?? gx
                let minY = cells.map { $0.1 }.min() ?? gy
                let maxY = cells.map { $0.1 }.max() ?? gy
                let centerX = CGFloat(minX + maxX + 1) * CGFloat(cellSize) / 2
                let centerY = CGFloat(minY + maxY + 1) * CGFloat(cellSize) / 2
                let side = max(CGFloat(max(maxX - minX + 1, maxY - minY + 1) * cellSize + 20), 28)
                let avgDiff = diffSum / Float(cells.count)
                let score = min(1, avgDiff * 5.2 + Float(cells.count <= 4 ? 0.18 : 0.08))
                regions.append(SuspectRegion(
                    boundingBox: CGRect(x: centerX - side / 2, y: centerY - side / 2, width: side, height: side),
                    confidence: max(0.05, score * CandidateSource.motion.weight),
                    source: .motion
                ))
            }
        }

        return regions
    }

    private func spatiallyDiverse(_ candidates: [SuspectRegion], imageSize: CGSize) -> [SuspectRegion] {
        guard imageSize.width > 0, imageSize.height > 0, candidates.count > maxCandidates else {
            return candidates
        }

        var selected: [SuspectRegion] = []
        var occupied = Set<String>()
        let columns: CGFloat = 3
        let rows: CGFloat = 4

        for candidate in candidates {
            let column = min(Int(columns - 1), max(0, Int(candidate.center.x / max(1, imageSize.width / columns))))
            let row = min(Int(rows - 1), max(0, Int(candidate.center.y / max(1, imageSize.height / rows))))
            let key = "\(column)-\(row)"
            if !occupied.contains(key) {
                selected.append(candidate)
                occupied.insert(key)
            }
            if selected.count >= maxCandidates { break }
        }

        if selected.count < maxCandidates {
            for candidate in candidates where !selected.contains(candidate) {
                selected.append(candidate)
                if selected.count >= maxCandidates { break }
            }
        }

        return selected + candidates.filter { !selected.contains($0) }
    }

    private func expandedClassifierRegion(_ rect: CGRect) -> CGRect {
        let side = max(max(rect.width, rect.height) * 1.85, 48)
        return CGRect(
            x: rect.midX - side / 2,
            y: rect.midY - side / 2,
            width: side,
            height: side
        )
    }

    private func adaptiveLocalContrastThreshold(frameStats: BrightnessStats) -> Float {
        var threshold = localContrastThreshold
        if frameStats.mean < 0.34 {
            threshold *= 0.68
        }
        if frameStats.variance > backgroundVarianceThreshold * 7 {
            threshold *= 0.72
        }
        return max(0.025, min(localContrastThreshold, threshold))
    }

    private func adaptiveBackgroundVarianceThreshold(frameStats: BrightnessStats) -> Float {
        var threshold = backgroundVarianceThreshold
        if frameStats.mean < 0.34 {
            threshold *= 1.6
        }
        if frameStats.variance > backgroundVarianceThreshold * 7 {
            threshold *= 2.2
        }
        return max(backgroundVarianceThreshold, min(0.065, threshold))
    }

    private func makeCandidate(x: Int, y: Int, size: CGFloat, score: Float, source: CandidateSource) -> SuspectRegion {
        SuspectRegion(
            boundingBox: CGRect(
                x: CGFloat(x) - size / 2,
                y: CGFloat(y) - size / 2,
                width: size,
                height: size
            ),
            confidence: max(0.05, min(1, score * source.weight)),
            source: source
        )
    }

    private func stabilize(_ candidates: [SuspectRegion]) -> [SuspectRegion] {
        var matchedTrackIDs = Set<UUID>()
        var matchedCandidateIndices = Set<Int>()

        for (index, candidate) in candidates.enumerated() {
            guard let trackIndex = bestTrackIndex(for: candidate, excluding: matchedTrackIDs) else {
                continue
            }

            tracks[trackIndex].rect = blend(tracks[trackIndex].rect, candidate.boundingBox, factor: 0.42)
            tracks[trackIndex].score = max(tracks[trackIndex].score * 0.72, rankedScore(candidate))
            tracks[trackIndex].source = dominantSource(existing: tracks[trackIndex].source, incoming: candidate.source)
            tracks[trackIndex].hits += 1
            tracks[trackIndex].misses = 0
            tracks[trackIndex].lastSeen = Date()
            matchedTrackIDs.insert(tracks[trackIndex].id)
            matchedCandidateIndices.insert(index)
        }

        for index in tracks.indices where !matchedTrackIDs.contains(tracks[index].id) {
            tracks[index].misses += 1
            tracks[index].score *= 0.78
        }

        for (index, candidate) in candidates.enumerated() where !matchedCandidateIndices.contains(index) {
            tracks.append(
                CandidateTrack(
                    rect: candidate.boundingBox,
                    score: rankedScore(candidate),
                    source: candidate.source
                )
            )
        }

        tracks.removeAll { $0.misses > maxTrackMisses || $0.score < 0.04 }

        let stableRegions = tracks.map { track -> SuspectRegion in
            let stability = min(1, Float(track.hits) / 4.0)
            let score = min(1, track.score * (0.55 + stability * 0.55))
            return SuspectRegion(
                boundingBox: track.rect,
                confidence: score,
                source: track.hits > 1 ? .fused : track.source,
                stability: stability
            )
        }

        return nonMaximumSuppressed(
            stableRegions.sorted { rankedScore($0) > rankedScore($1) },
            iouThreshold: 0.30
        )
    }

    private func bestTrackIndex(for candidate: SuspectRegion, excluding matchedIDs: Set<UUID>) -> Int? {
        var bestIndex: Int?
        var bestScore: CGFloat = 0

        for index in tracks.indices where !matchedIDs.contains(tracks[index].id) {
            let iou = intersectionOverUnion(candidate.boundingBox, tracks[index].rect)
            let centerDistance = hypot(candidate.center.x - tracks[index].rect.midX, candidate.center.y - tracks[index].rect.midY)
            let maxSide = max(candidate.boundingBox.width, candidate.boundingBox.height, tracks[index].rect.width, tracks[index].rect.height)
            let centerThreshold = max(28, maxSide * 1.9)
            let centerScore = max(0, 1 - centerDistance / centerThreshold)
            let score = iou * 1.5 + centerScore * 0.85

            if (iou > 0.18 || centerDistance < centerThreshold) && score > bestScore {
                bestScore = score
                bestIndex = index
            }
        }

        return bestIndex
    }

    private func rankedScore(_ candidate: SuspectRegion) -> Float {
        min(1, max(0, candidate.confidence) * 0.78 + candidate.stability * 0.22)
    }

    private func dominantSource(existing: CandidateSource, incoming: CandidateSource) -> CandidateSource {
        existing.weight >= incoming.weight ? existing : incoming
    }

    private func blend(_ lhs: CGRect, _ rhs: CGRect, factor: CGFloat) -> CGRect {
        CGRect(
            x: lhs.origin.x * (1 - factor) + rhs.origin.x * factor,
            y: lhs.origin.y * (1 - factor) + rhs.origin.y * factor,
            width: lhs.width * (1 - factor) + rhs.width * factor,
            height: lhs.height * (1 - factor) + rhs.height * factor
        )
    }

    private func nonMaximumSuppressed(_ candidates: [SuspectRegion], iouThreshold: CGFloat) -> [SuspectRegion] {
        var selected: [SuspectRegion] = []
        for candidate in candidates.sorted(by: { rankedScore($0) > rankedScore($1) }) {
            if !selected.contains(where: { intersectionOverUnion(candidate.boundingBox, $0.boundingBox) >= iouThreshold }) {
                selected.append(candidate)
            }
        }
        return selected
    }

    private func intersectionOverUnion(_ lhs: CGRect, _ rhs: CGRect) -> CGFloat {
        let intersection = lhs.intersection(rhs)
        guard !intersection.isNull else { return 0 }
        let intersectionArea = intersection.width * intersection.height
        let unionArea = lhs.width * lhs.height + rhs.width * rhs.height - intersectionArea
        return unionArea > 0 ? intersectionArea / unionArea : 0
    }

    private func sampleStats(
        buffer: UnsafePointer<UInt8>,
        bytesPerRow: Int,
        centerX: Int,
        centerY: Int,
        radius: Int
    ) -> BrightnessStats {
        var values: [Float] = []
        for dy in stride(from: -radius, through: radius, by: max(1, radius / 2)) {
            for dx in stride(from: -radius, through: radius, by: max(1, radius / 2)) {
                values.append(brightness(buffer: buffer, bytesPerRow: bytesPerRow, x: centerX + dx, y: centerY + dy))
            }
        }
        return BrightnessStats(values: values)
    }

    private func sampleRingStats(
        buffer: UnsafePointer<UInt8>,
        bytesPerRow: Int,
        centerX: Int,
        centerY: Int,
        innerRadius: Int,
        outerRadius: Int
    ) -> BrightnessStats {
        var values: [Float] = []
        let step = 6
        for dy in stride(from: -outerRadius, through: outerRadius, by: step) {
            for dx in stride(from: -outerRadius, through: outerRadius, by: step) {
                let distance = sqrt(Float(dx * dx + dy * dy))
                if distance >= Float(innerRadius), distance <= Float(outerRadius) {
                    values.append(brightness(buffer: buffer, bytesPerRow: bytesPerRow, x: centerX + dx, y: centerY + dy))
                }
            }
        }
        return BrightnessStats(values: values)
    }

    private func sampleFrameStats(
        buffer: UnsafePointer<UInt8>,
        bytesPerRow: Int,
        width: Int,
        height: Int
    ) -> BrightnessStats {
        var values: [Float] = []
        let stepX = max(24, width / 18)
        let stepY = max(24, height / 18)
        for y in stride(from: stepY / 2, to: height, by: stepY) {
            for x in stride(from: stepX / 2, to: width, by: stepX) {
                values.append(brightness(buffer: buffer, bytesPerRow: bytesPerRow, x: x, y: y))
            }
        }
        return BrightnessStats(values: values)
    }

    private func brightness(buffer: UnsafePointer<UInt8>, bytesPerRow: Int, x: Int, y: Int) -> Float {
        let offset = y * bytesPerRow + x * 4
        let b = Float(buffer[offset])
        let g = Float(buffer[offset + 1])
        let r = Float(buffer[offset + 2])
        return (r * 0.299 + g * 0.587 + b * 0.114) / 255.0
    }
}

private struct CandidateTrack {
    let id = UUID()
    var rect: CGRect
    var score: Float
    var source: CandidateSource
    var hits = 1
    var misses = 0
    var lastSeen = Date()
}

private struct MotionGrid {
    let width: Int
    let height: Int
    let values: [Float]
}

private struct BrightnessStats {
    let mean: Float
    let variance: Float

    init(values: [Float]) {
        guard !values.isEmpty else {
            mean = 0
            variance = 1
            return
        }
        let computedMean = values.reduce(0, +) / Float(values.count)
        mean = computedMean
        variance = values.reduce(0) { $0 + pow($1 - computedMean, 2) } / Float(values.count)
    }
}
