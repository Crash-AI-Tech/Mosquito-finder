import CoreGraphics
import CoreVideo
import Foundation

/// Fixed-camera Stage 1 detector. It finds and tracks small moving regions; it
/// deliberately does not claim that a moving region is a mosquito.
final class StationaryFlightDetector {
    var calibrationFrameCount = 24
    var minimumFrameInterval: TimeInterval = 1.0 / 45.0
    var maximumTracks = 12

    private var gridWidth = 0
    private var gridHeight = 0
    private var samplingStep = 2
    private var background: [Float] = []
    private var previous: [Float] = []
    private var calibrationFrames = 0
    private var lastProcessedTimestamp: TimeInterval?
    private var tracks: [FlightTrackState] = []
    private var unstableFrameCount = 0
    private var processedFrames = 0
    private var rejectedSceneChanges = 0

    func reset() {
        gridWidth = 0
        gridHeight = 0
        background.removeAll(keepingCapacity: false)
        previous.removeAll(keepingCapacity: false)
        calibrationFrames = 0
        lastProcessedTimestamp = nil
        tracks.removeAll(keepingCapacity: false)
        unstableFrameCount = 0
    }

    func process(pixelBuffer: CVPixelBuffer, timestamp: TimeInterval) -> StationaryDetectorOutput? {
        if let lastProcessedTimestamp,
           timestamp - lastProcessedTimestamp < minimumFrameInterval {
            return nil
        }
        lastProcessedTimestamp = timestamp

        let startedAt = Date()
        let frameWidth = CVPixelBufferGetWidth(pixelBuffer)
        let frameHeight = CVPixelBufferGetHeight(pixelBuffer)
        guard frameWidth > 0, frameHeight > 0,
              let samples = makeLumaGrid(from: pixelBuffer) else {
            return nil
        }

        processedFrames += 1
        let frameSize = CGSize(width: frameWidth, height: frameHeight)

        if background.count != samples.count || previous.count != samples.count {
            background = samples
            previous = samples
            calibrationFrames = 1
            tracks.removeAll(keepingCapacity: true)
            return calibrationOutput(frameSize: frameSize, startedAt: startedAt)
        }

        if calibrationFrames < calibrationFrameCount {
            let alpha: Float = calibrationFrames < 8 ? 0.32 : 0.16
            for index in samples.indices {
                background[index] += (samples[index] - background[index]) * alpha
            }
            previous = samples
            calibrationFrames += 1
            return calibrationOutput(frameSize: frameSize, startedAt: startedAt)
        }

        var signedChange: Float = 0
        for index in samples.indices {
            signedChange += samples[index] - background[index]
        }
        let globalChange = signedChange / Float(max(1, samples.count))

        var residuals = Array(repeating: Float(0), count: samples.count)
        var noiseFloor: Float = 0
        for index in samples.indices {
            let residual = abs((samples[index] - background[index]) - globalChange)
            residuals[index] = residual
            noiseFloor += residual
        }
        noiseFloor /= Float(max(1, samples.count))

        let threshold = min(0.18, max(0.038, noiseFloor * 4.2 + 0.018))
        let temporalThreshold = max(0.018, threshold * 0.42)
        let margin = max(3, 12 / samplingStep)
        var foregroundMask = Array(repeating: false, count: samples.count)
        var foregroundPixels = 0

        if gridWidth > margin * 2, gridHeight > margin * 2 {
            for y in margin..<(gridHeight - margin) {
                let row = y * gridWidth
                for x in margin..<(gridWidth - margin) {
                    let index = row + x
                    let temporalChange = abs(samples[index] - previous[index])
                    if residuals[index] > threshold && temporalChange > temporalThreshold {
                        foregroundMask[index] = true
                        foregroundPixels += 1
                    }
                }
            }
        }

        let foregroundRatio = Float(foregroundPixels) / Float(max(1, samples.count))
        let sceneIsUnstable = abs(globalChange) > 0.075 || foregroundRatio > 0.065 || noiseFloor > 0.055

        if sceneIsUnstable {
            unstableFrameCount += 1
            rejectedSceneChanges += 1
            for index in samples.indices {
                background[index] += (samples[index] - background[index]) * 0.18
            }
            previous = samples
            tracks.removeAll(keepingCapacity: true)

            if unstableFrameCount >= 3 {
                calibrationFrames = max(1, calibrationFrameCount / 3)
            }

            return StationaryDetectorOutput(
                tracks: [],
                primaryTrack: nil,
                landingCandidate: nil,
                diagnostics: diagnostics(
                    frameSize: frameSize,
                    foregroundCount: 0,
                    qualifiedTrackCount: 0,
                    globalChange: globalChange,
                    noiseFloor: noiseFloor,
                    startedAt: startedAt
                ),
                isSceneStable: false
            )
        }

        unstableFrameCount = 0
        var componentMask = foregroundMask
        let motionRegions = connectedMotionRegions(
            mask: &componentMask,
            residuals: residuals,
            frameSize: frameSize
        )

        let landingCandidate = updateTracks(
            with: motionRegions,
            timestamp: timestamp,
            frameSize: frameSize
        )

        // A moving foreground pixel is updated very slowly so a stopped insect
        // remains visible long enough for landing verification.
        for index in samples.indices {
            let alpha: Float = foregroundMask[index] ? 0.001 : 0.018
            background[index] += (samples[index] - background[index]) * alpha
        }
        previous = samples

        let snapshots = tracks
            .filter { $0.hits >= 2 && $0.misses <= 3 }
            .map { snapshot(for: $0, frameSize: frameSize) }
            .sorted { lhs, rhs in
                if lhs.isFlightLike != rhs.isFlightLike { return lhs.isFlightLike }
                return lhs.confidence > rhs.confidence
            }
        let primary = snapshots.first

        return StationaryDetectorOutput(
            tracks: snapshots,
            primaryTrack: primary,
            landingCandidate: landingCandidate,
            diagnostics: diagnostics(
                frameSize: frameSize,
                foregroundCount: motionRegions.count,
                qualifiedTrackCount: snapshots.filter(\.isFlightLike).count,
                globalChange: globalChange,
                noiseFloor: noiseFloor,
                startedAt: startedAt
            ),
            isSceneStable: true
        )
    }

    private func makeLumaGrid(from pixelBuffer: CVPixelBuffer) -> [Float]? {
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let step = max(width, height) >= 3_000 ? 3 : 2
        let nextGridWidth = max(1, width / step)
        let nextGridHeight = max(1, height / step)

        if nextGridWidth != gridWidth || nextGridHeight != gridHeight || step != samplingStep {
            gridWidth = nextGridWidth
            gridHeight = nextGridHeight
            samplingStep = step
        }

        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let isPlanar = CVPixelBufferIsPlanar(pixelBuffer)
        let baseAddress: UnsafeMutableRawPointer?
        let bytesPerRow: Int
        let bytesPerPixel: Int

        if isPlanar, CVPixelBufferGetPlaneCount(pixelBuffer) > 0 {
            baseAddress = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0)
            bytesPerRow = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
            bytesPerPixel = 1
        } else {
            baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer)
            bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
            bytesPerPixel = 4
        }

        guard let baseAddress else { return nil }
        let bytes = baseAddress.assumingMemoryBound(to: UInt8.self)
        var result = Array(repeating: Float(0), count: gridWidth * gridHeight)

        for gy in 0..<gridHeight {
            let sourceY = min(height - 1, gy * step)
            for gx in 0..<gridWidth {
                let sourceX = min(width - 1, gx * step)
                var sum = 0
                var count = 0

                for dy in 0..<step where sourceY + dy < height {
                    let row = bytes.advanced(by: (sourceY + dy) * bytesPerRow)
                    for dx in 0..<step where sourceX + dx < width {
                        let x = sourceX + dx
                        if bytesPerPixel == 1 {
                            sum += Int(row[x])
                        } else {
                            let pixel = row.advanced(by: x * bytesPerPixel)
                            // BGRA to luma, integer approximation of Rec. 601.
                            sum += (29 * Int(pixel[0]) + 150 * Int(pixel[1]) + 77 * Int(pixel[2])) >> 8
                        }
                        count += 1
                    }
                }

                result[gy * gridWidth + gx] = Float(sum) / Float(max(1, count) * 255)
            }
        }

        return result
    }

    private func connectedMotionRegions(
        mask: inout [Bool],
        residuals: [Float],
        frameSize: CGSize
    ) -> [MotionRegion] {
        var regions: [MotionRegion] = []
        var queue: [Int] = []
        queue.reserveCapacity(256)
        let maxCells = 360
        let maxPixelSide = min(frameSize.width, frameSize.height) * 0.18

        for start in mask.indices where mask[start] {
            queue.removeAll(keepingCapacity: true)
            queue.append(start)
            mask[start] = false
            var cursor = 0
            var minX = start % gridWidth
            var maxX = minX
            var minY = start / gridWidth
            var maxY = minY
            var residualSum: Float = 0
            var cellCount = 0

            while cursor < queue.count {
                let index = queue[cursor]
                cursor += 1
                let x = index % gridWidth
                let y = index / gridWidth
                minX = min(minX, x)
                maxX = max(maxX, x)
                minY = min(minY, y)
                maxY = max(maxY, y)
                residualSum += residuals[index]
                cellCount += 1

                for ny in max(0, y - 1)...min(gridHeight - 1, y + 1) {
                    for nx in max(0, x - 1)...min(gridWidth - 1, x + 1) {
                        let neighbor = ny * gridWidth + nx
                        if mask[neighbor] {
                            mask[neighbor] = false
                            queue.append(neighbor)
                        }
                    }
                }
            }

            guard (1...maxCells).contains(cellCount) else { continue }
            let pixelWidth = CGFloat(maxX - minX + 1) * CGFloat(samplingStep)
            let pixelHeight = CGFloat(maxY - minY + 1) * CGFloat(samplingStep)
            guard max(pixelWidth, pixelHeight) <= maxPixelSide else { continue }

            let padding = CGFloat(max(8, samplingStep * 3))
            let rawRect = CGRect(
                x: CGFloat(minX * samplingStep) - padding,
                y: CGFloat(minY * samplingStep) - padding,
                width: pixelWidth + padding * 2,
                height: pixelHeight + padding * 2
            )
            let frameRect = CGRect(origin: .zero, size: frameSize)
            let rect = rawRect.intersection(frameRect)
            guard !rect.isNull, rect.width > 0, rect.height > 0 else { continue }

            let averageResidual = residualSum / Float(cellCount)
            let compactness = Float(cellCount) / Float(max(1, (maxX - minX + 1) * (maxY - minY + 1)))
            let sizeScore = 1 - min(1, Float(cellCount) / Float(maxCells))
            let confidence = min(1, averageResidual * 5.5 + compactness * 0.18 + sizeScore * 0.12)
            regions.append(MotionRegion(rect: rect, confidence: confidence))
        }

        return Array(regions.sorted { $0.confidence > $1.confidence }.prefix(maximumTracks * 2))
    }

    private func updateTracks(
        with regions: [MotionRegion],
        timestamp: TimeInterval,
        frameSize: CGSize
    ) -> LandingCandidate? {
        var matchedTrackIDs = Set<UUID>()
        var matchedRegionIndices = Set<Int>()
        let baseGate = max(70, min(frameSize.width, frameSize.height) * 0.11)

        for (regionIndex, region) in regions.enumerated() {
            var bestTrackIndex: Int?
            var bestCost = CGFloat.greatestFiniteMagnitude

            for index in tracks.indices where !matchedTrackIDs.contains(tracks[index].id) {
                let track = tracks[index]
                let dt = max(1.0 / 120.0, min(0.25, timestamp - track.lastTimestamp))
                let predicted = CGPoint(
                    x: track.center.x + track.velocity.dx * dt,
                    y: track.center.y + track.velocity.dy * dt
                )
                let distance = hypot(region.center.x - predicted.x, region.center.y - predicted.y)
                let gate = baseGate + min(baseGate, hypot(track.velocity.dx, track.velocity.dy) * dt * 0.75)
                guard distance <= gate else { continue }

                let sizeDelta = abs(region.rect.width - track.boundingBox.width)
                    + abs(region.rect.height - track.boundingBox.height)
                let cost = distance / gate + sizeDelta / max(24, track.boundingBox.width + track.boundingBox.height) * 0.22
                if cost < bestCost {
                    bestCost = cost
                    bestTrackIndex = index
                }
            }

            guard let bestTrackIndex else { continue }
            updateTrack(&tracks[bestTrackIndex], with: region, timestamp: timestamp)
            matchedTrackIDs.insert(tracks[bestTrackIndex].id)
            matchedRegionIndices.insert(regionIndex)
        }

        for index in tracks.indices where !matchedTrackIDs.contains(tracks[index].id) {
            tracks[index].misses += 1
            tracks[index].confidence *= 0.94
        }

        for (regionIndex, region) in regions.enumerated() where !matchedRegionIndices.contains(regionIndex) {
            tracks.append(FlightTrackState(region: region, timestamp: timestamp))
        }

        var landingCandidate: LandingCandidate?
        for index in tracks.indices {
            let snapshot = snapshot(for: tracks[index], frameSize: frameSize)
            let edgeMargin = min(frameSize.width, frameSize.height) * 0.055
            let isAwayFromEdge = snapshot.center.x > edgeMargin
                && snapshot.center.x < frameSize.width - edgeMargin
                && snapshot.center.y > edgeMargin
                && snapshot.center.y < frameSize.height - edgeMargin

            if snapshot.isFlightLike,
               tracks[index].misses == 5,
               !tracks[index].didEmitLanding,
               isAwayFromEdge {
                tracks[index].didEmitLanding = true
                let side = max(120, min(frameSize.width, frameSize.height) * 0.13)
                let landingRect = CGRect(
                    x: snapshot.center.x - side / 2,
                    y: snapshot.center.y - side / 2,
                    width: side,
                    height: side
                ).intersection(CGRect(origin: .zero, size: frameSize))
                landingCandidate = LandingCandidate(
                    trackID: snapshot.id,
                    boundingBox: landingRect,
                    confidence: snapshot.confidence,
                    lastMotionPoint: snapshot.center,
                    detectedAt: Date()
                )
                break
            }
        }

        tracks.removeAll { $0.misses > 14 || $0.confidence < 0.05 }
        if tracks.count > maximumTracks * 2 {
            tracks = Array(tracks.sorted { $0.confidence > $1.confidence }.prefix(maximumTracks * 2))
        }
        return landingCandidate
    }

    private func updateTrack(_ track: inout FlightTrackState, with region: MotionRegion, timestamp: TimeInterval) {
        let dt = max(1.0 / 120.0, min(0.25, timestamp - track.lastTimestamp))
        let oldCenter = track.center
        let displacement = CGVector(dx: region.center.x - oldCenter.x, dy: region.center.y - oldCenter.y)
        let instantaneousVelocity = CGVector(dx: displacement.dx / dt, dy: displacement.dy / dt)
        let velocityBlend: CGFloat = track.hits < 2 ? 0.75 : 0.42
        track.velocity = CGVector(
            dx: track.velocity.dx * (1 - velocityBlend) + instantaneousVelocity.dx * velocityBlend,
            dy: track.velocity.dy * (1 - velocityBlend) + instantaneousVelocity.dy * velocityBlend
        )
        track.totalDistance += hypot(displacement.dx, displacement.dy)
        track.center = region.center
        track.boundingBox = blend(track.boundingBox, region.rect, factor: 0.58)
        track.confidence = min(1, max(track.confidence * 0.82, region.confidence) + 0.035)
        track.lastTimestamp = timestamp
        track.hits += 1
        track.misses = 0
        track.history.append(region.center)
        if track.history.count > 32 {
            track.history.removeFirst(track.history.count - 32)
        }
    }

    private func snapshot(for track: FlightTrackState, frameSize: CGSize) -> FlightTrackSnapshot {
        let duration = max(0, track.lastTimestamp - track.createdTimestamp)
        let meanSpeed = duration > 0 ? track.totalDistance / duration : 0
        let shortEdge = min(frameSize.width, frameSize.height)
        let areaRatio = track.boundingBox.width * track.boundingBox.height
            / max(1, frameSize.width * frameSize.height)
        let minimumDistance = max(18, shortEdge * 0.012)
        let flightLike = track.hits >= 4
            && duration >= 0.12
            && track.totalDistance >= minimumDistance
            && meanSpeed >= max(24, shortEdge * 0.025)
            && meanSpeed <= shortEdge * 5.5
            && areaRatio < 0.012
            && max(track.boundingBox.width, track.boundingBox.height) < shortEdge * 0.18

        let persistence = min(1, Float(track.hits) / 12)
        let travel = min(1, Float(track.totalDistance / max(1, shortEdge * 0.12)))
        let flightBonus: Float = flightLike ? 0.18 : 0
        let confidence = min(1, track.confidence * 0.52 + persistence * 0.24 + travel * 0.18 + flightBonus)

        return FlightTrackSnapshot(
            id: track.id,
            boundingBox: track.boundingBox,
            points: track.history,
            confidence: confidence,
            duration: duration,
            speed: meanSpeed,
            isFlightLike: flightLike,
            missedFrames: track.misses
        )
    }

    private func calibrationOutput(frameSize: CGSize, startedAt: Date) -> StationaryDetectorOutput {
        StationaryDetectorOutput(
            tracks: [],
            primaryTrack: nil,
            landingCandidate: nil,
            diagnostics: diagnostics(
                frameSize: frameSize,
                foregroundCount: 0,
                qualifiedTrackCount: 0,
                globalChange: 0,
                noiseFloor: 0,
                startedAt: startedAt
            ),
            isSceneStable: true
        )
    }

    private func diagnostics(
        frameSize: CGSize,
        foregroundCount: Int,
        qualifiedTrackCount: Int,
        globalChange: Float,
        noiseFloor: Float,
        startedAt: Date
    ) -> StationaryDetectorDiagnostics {
        StationaryDetectorDiagnostics(
            frameSize: frameSize,
            calibrationProgress: min(1, Double(calibrationFrames) / Double(max(1, calibrationFrameCount))),
            foregroundRegionCount: foregroundCount,
            activeTrackCount: tracks.filter { $0.misses <= 3 }.count,
            qualifiedTrackCount: qualifiedTrackCount,
            globalChange: globalChange,
            noiseFloor: noiseFloor,
            processingTime: Date().timeIntervalSince(startedAt),
            processedFrames: processedFrames,
            rejectedSceneChanges: rejectedSceneChanges
        )
    }

    private func blend(_ lhs: CGRect, _ rhs: CGRect, factor: CGFloat) -> CGRect {
        CGRect(
            x: lhs.origin.x * (1 - factor) + rhs.origin.x * factor,
            y: lhs.origin.y * (1 - factor) + rhs.origin.y * factor,
            width: lhs.width * (1 - factor) + rhs.width * factor,
            height: lhs.height * (1 - factor) + rhs.height * factor
        )
    }
}

private struct MotionRegion {
    var rect: CGRect
    var confidence: Float

    var center: CGPoint {
        CGPoint(x: rect.midX, y: rect.midY)
    }
}

private struct FlightTrackState {
    let id = UUID()
    var center: CGPoint
    var boundingBox: CGRect
    var velocity: CGVector = .zero
    var confidence: Float
    var createdTimestamp: TimeInterval
    var lastTimestamp: TimeInterval
    var hits = 1
    var misses = 0
    var totalDistance: CGFloat = 0
    var history: [CGPoint]
    var didEmitLanding = false

    init(region: MotionRegion, timestamp: TimeInterval) {
        center = region.center
        boundingBox = region.rect
        confidence = region.confidence
        createdTimestamp = timestamp
        lastTimestamp = timestamp
        history = [region.center]
    }
}
