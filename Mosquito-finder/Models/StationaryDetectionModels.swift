import CoreGraphics
import Foundation
import SwiftUI

enum StationaryDetectionPhase: Equatable {
    case positioning
    case calibrating
    case monitoring
    case motionDetected
    case trackingFlight
    case cameraMoved
    case landingLocated
    case verifying
    case confirmed

    var titleKey: LocalizedStringKey {
        switch self {
        case .positioning: return "Mount the phone"
        case .calibrating: return "Calibrating the room"
        case .monitoring: return "Watching for flight"
        case .motionDetected: return "Motion detected"
        case .trackingFlight: return "Tracking a possible flying insect"
        case .cameraMoved: return "Camera movement detected"
        case .landingLocated: return "Possible landing area"
        case .verifying: return "Checking the landing area"
        case .confirmed: return "Mosquito confirmed"
        }
    }

    var detailKey: LocalizedStringKey {
        switch self {
        case .positioning:
            return "Place the phone on a stable support with a clear view of the room."
        case .calibrating:
            return "Keep people, curtains, and the phone still while the background is learned."
        case .monitoring:
            return "The app is looking for small moving objects, not declaring a mosquito yet."
        case .motionDetected:
            return "A small movement is being checked across several frames."
        case .trackingFlight:
            return "Keep the scene unchanged while the possible insect remains in view."
        case .cameraMoved:
            return "Do not touch the phone. Background calibration will restart automatically."
        case .landingLocated:
            return "The movement stopped near this area. Move closer before final identification."
        case .verifying:
            return "The Stage 2 classifier is checking the last visible area."
        case .confirmed:
            return "The landing area also passed the mosquito classifier."
        }
    }

    var systemImage: String {
        switch self {
        case .positioning: return "iphone.gen3.radiowaves.left.and.right"
        case .calibrating: return "viewfinder"
        case .monitoring: return "camera.metering.matrix"
        case .motionDetected: return "waveform.path.ecg"
        case .trackingFlight: return "scope"
        case .cameraMoved: return "hand.raised.fill"
        case .landingLocated: return "mappin.and.ellipse"
        case .verifying: return "checkmark.seal"
        case .confirmed: return "checkmark.seal.fill"
        }
    }

    var tint: Color {
        switch self {
        case .positioning, .cameraMoved: return .orange
        case .calibrating, .verifying: return .cyan
        case .monitoring: return .green
        case .motionDetected: return .yellow
        case .trackingFlight: return .orange
        case .landingLocated: return .yellow
        case .confirmed: return .red
        }
    }
}

struct FlightTrackSnapshot: Identifiable, Equatable {
    let id: UUID
    var boundingBox: CGRect
    var points: [CGPoint]
    var confidence: Float
    var duration: TimeInterval
    var speed: CGFloat
    var isFlightLike: Bool
    var missedFrames: Int

    var center: CGPoint {
        CGPoint(x: boundingBox.midX, y: boundingBox.midY)
    }
}

struct LandingCandidate: Equatable {
    let trackID: UUID
    var boundingBox: CGRect
    var confidence: Float
    var lastMotionPoint: CGPoint
    var detectedAt: Date
}

struct StationaryDetectorDiagnostics: Equatable {
    var frameSize: CGSize = .zero
    var calibrationProgress: Double = 0
    var foregroundRegionCount = 0
    var activeTrackCount = 0
    var qualifiedTrackCount = 0
    var globalChange: Float = 0
    var noiseFloor: Float = 0
    var processingTime: TimeInterval = 0
    var processedFrames = 0
    var rejectedSceneChanges = 0

    var processingTimeText: String {
        String(format: "%.0fms", processingTime * 1_000)
    }
}

struct StationaryDetectorOutput {
    var tracks: [FlightTrackSnapshot]
    var primaryTrack: FlightTrackSnapshot?
    var landingCandidate: LandingCandidate?
    var diagnostics: StationaryDetectorDiagnostics
    var isSceneStable: Bool
}
