import CoreVideo
import Foundation

private func makeFrame(width: Int, height: Int, dot: CGRect?) -> CVPixelBuffer {
    var buffer: CVPixelBuffer?
    let attributes: [CFString: Any] = [
        kCVPixelBufferCGImageCompatibilityKey: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey: true
    ]
    CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32BGRA,
        attributes as CFDictionary,
        &buffer
    )
    let pixelBuffer = buffer!
    CVPixelBufferLockBaseAddress(pixelBuffer, [])
    let rowBytes = CVPixelBufferGetBytesPerRow(pixelBuffer)
    let bytes = CVPixelBufferGetBaseAddress(pixelBuffer)!.assumingMemoryBound(to: UInt8.self)

    for y in 0..<height {
        let row = bytes.advanced(by: y * rowBytes)
        for x in 0..<width {
            let isDot = dot?.contains(CGPoint(x: x, y: y)) == true
            let value: UInt8 = isDot ? 28 : 178
            row[x * 4] = value
            row[x * 4 + 1] = value
            row[x * 4 + 2] = value
            row[x * 4 + 3] = 255
        }
    }

    CVPixelBufferUnlockBaseAddress(pixelBuffer, [])
    return pixelBuffer
}

@main
struct StationaryFlightDetectorHarness {
    static func main() {
        let detector = StationaryFlightDetector()
        detector.minimumFrameInterval = 0
        detector.calibrationFrameCount = 12
        let width = 320
        let height = 240
        var timestamp = 0.0

        for _ in 0..<14 {
            _ = detector.process(
                pixelBuffer: makeFrame(width: width, height: height, dot: nil),
                timestamp: timestamp
            )
            timestamp += 1.0 / 60.0
        }

        var sawFlightTrack = false
        for index in 0..<12 {
            let x = 42 + index * 11
            let output = detector.process(
                pixelBuffer: makeFrame(
                    width: width,
                    height: height,
                    dot: CGRect(x: x, y: 96 + (index % 3) * 3, width: 6, height: 6)
                ),
                timestamp: timestamp
            )
            timestamp += 1.0 / 60.0
            sawFlightTrack = sawFlightTrack || output?.tracks.contains(where: \.isFlightLike) == true
        }

        var landing: LandingCandidate?
        let stoppedDot = CGRect(x: 42 + 11 * 11, y: 102, width: 6, height: 6)
        for _ in 0..<8 {
            let output = detector.process(
                pixelBuffer: makeFrame(width: width, height: height, dot: stoppedDot),
                timestamp: timestamp
            )
            timestamp += 1.0 / 60.0
            landing = landing ?? output?.landingCandidate
        }

        guard sawFlightTrack, landing != nil else {
            fputs("FAIL sawFlightTrack=\(sawFlightTrack) landing=\(landing != nil)\n", stderr)
            exit(1)
        }
        print("PASS flight track and landing candidate detected")
    }
}
