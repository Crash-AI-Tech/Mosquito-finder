import AVFoundation
import Combine
import CoreGraphics
import Foundation
import UIKit

@MainActor
final class StationaryDetectionViewModel: ObservableObject {
    @Published var isSessionActive = false
    @Published var phase: StationaryDetectionPhase = .positioning
    @Published var tracks: [FlightTrackSnapshot] = []
    @Published var primaryTrack: FlightTrackSnapshot?
    @Published var landingCandidate: LandingCandidate?
    @Published var classificationResult: ClassificationResult?
    @Published var diagnostics = StationaryDetectorDiagnostics()
    @Published var nativeImageSize = CGSize(width: 1080, height: 1920)
    @Published var frozenFrame: UIImage?
    @Published var isFlashlightOn = false
    @Published var elapsedTime = "00:00"
    @Published var errorMessage: String?

    let cameraController = CameraController(captureProfile: .stationaryFlight)

    private let detector = StationaryFlightDetector()
    private let classifier = Stage2Classifier()
    private let motionDetector = MotionDetector()
    private let flashlightManager = FlashlightManager()
    private let hapticsEngine = HapticsEngine()
    private var cancellables = Set<AnyCancellable>()
    private var sessionStartedAt: Date?
    private var sessionTimer: Timer?
    private var stableSince: TimeInterval?
    private var wasDeviceMoving = false
    private var hasLockedCapture = false
    private var isPausedForLanding = false
    private var lastMotionHaptic = Date.distantPast

    init() {
        setupBindings()
        setupFrameHandler()
        classifier.apply(settings: RuntimeDetectionSettings.current)
    }

    func start() {
        guard !isSessionActive else { return }
        resetPublishedState()
        phase = .positioning

        cameraController.requestAccessAndConfigure { [weak self] success in
            guard let self, success else { return }
            self.flashlightManager.updateDevice(self.cameraController.captureDevice)
            self.cameraController.start()
            self.motionDetector.start()
            self.sessionStartedAt = Date()
            self.isSessionActive = true
            self.phase = .calibrating
            self.startTimer()
        }
    }

    func stop() {
        cameraController.stop()
        cameraController.unlockStationaryCapture()
        flashlightManager.turnOff()
        motionDetector.stop()
        detector.reset()
        stopTimer()
        isSessionActive = false
        isPausedForLanding = false
        hasLockedCapture = false
        stableSince = nil
        wasDeviceMoving = false
    }

    func toggleFlashlight() {
        flashlightManager.updateDevice(cameraController.captureDevice)
        flashlightManager.toggle()
    }

    func recalibrate() {
        isPausedForLanding = false
        landingCandidate = nil
        classificationResult = nil
        frozenFrame = nil
        tracks = []
        primaryTrack = nil
        hasLockedCapture = false
        cameraController.unlockStationaryCapture()
        detector.reset()
        phase = .calibrating
    }

    func markFalseAlarmAndResume() {
        saveLandingReview(label: "flight_false_positive")
        hapticsEngine.targetDismissed()
        recalibrate()
    }

    private func setupBindings() {
        cameraController.$error
            .receive(on: DispatchQueue.main)
            .compactMap { $0?.localizedDescription }
            .assign(to: &$errorMessage)

        flashlightManager.$isOn
            .receive(on: DispatchQueue.main)
            .assign(to: &$isFlashlightOn)
    }

    private func setupFrameHandler() {
        cameraController.onFrameCaptured = { [weak self] sampleBuffer in
            guard let self,
                  let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
                return
            }

            let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
            let safeTimestamp = timestamp.isFinite ? timestamp : Date().timeIntervalSinceReferenceDate
            let frameSize = CGSize(
                width: CVPixelBufferGetWidth(pixelBuffer),
                height: CVPixelBufferGetHeight(pixelBuffer)
            )

            DispatchQueue.main.async {
                if self.nativeImageSize != frameSize {
                    self.nativeImageSize = frameSize
                }
            }

            guard !self.isPausedForLanding else { return }

            if self.motionDetector.isShaking {
                self.handleDeviceMovement()
                return
            }

            if self.wasDeviceMoving {
                if self.stableSince == nil {
                    self.stableSince = safeTimestamp
                }
                guard safeTimestamp - (self.stableSince ?? safeTimestamp) >= 0.8 else {
                    return
                }
                self.wasDeviceMoving = false
                self.stableSince = nil
                self.detector.reset()
                DispatchQueue.main.async {
                    self.phase = .calibrating
                }
            }

            guard let output = self.detector.process(pixelBuffer: pixelBuffer, timestamp: safeTimestamp) else {
                return
            }

            if !output.isSceneStable {
                self.handleUnstableScene(output)
                return
            }

            if output.diagnostics.calibrationProgress < 1 {
                DispatchQueue.main.async {
                    self.diagnostics = output.diagnostics
                    self.phase = .calibrating
                }
                return
            }

            if !self.hasLockedCapture {
                self.hasLockedCapture = true
                self.cameraController.lockStationaryCapture()
            }

            if let landing = output.landingCandidate {
                self.handleLanding(
                    landing,
                    tracks: output.tracks,
                    diagnostics: output.diagnostics,
                    pixelBuffer: pixelBuffer
                )
                return
            }

            let nextPhase: StationaryDetectionPhase
            if output.primaryTrack?.isFlightLike == true {
                nextPhase = .trackingFlight
            } else if !output.tracks.isEmpty || output.diagnostics.foregroundRegionCount > 0 {
                nextPhase = .motionDetected
            } else {
                nextPhase = .monitoring
            }

            if nextPhase == .trackingFlight,
               Date().timeIntervalSince(self.lastMotionHaptic) > 2.5 {
                self.lastMotionHaptic = Date()
                self.hapticsEngine.suspectDetected()
            }

            DispatchQueue.main.async {
                self.tracks = output.tracks
                self.primaryTrack = output.primaryTrack
                self.diagnostics = output.diagnostics
                self.phase = nextPhase
            }
        }
    }

    private func handleDeviceMovement() {
        guard !wasDeviceMoving else { return }
        wasDeviceMoving = true
        stableSince = nil
        hasLockedCapture = false
        detector.reset()
        cameraController.unlockStationaryCapture()
        DispatchQueue.main.async {
            self.tracks = []
            self.primaryTrack = nil
            self.phase = .cameraMoved
        }
    }

    private func handleUnstableScene(_ output: StationaryDetectorOutput) {
        hasLockedCapture = false
        cameraController.unlockStationaryCapture()
        DispatchQueue.main.async {
            self.tracks = []
            self.primaryTrack = nil
            self.diagnostics = output.diagnostics
            self.phase = .cameraMoved
        }
    }

    private func handleLanding(
        _ landing: LandingCandidate,
        tracks: [FlightTrackSnapshot],
        diagnostics: StationaryDetectorDiagnostics,
        pixelBuffer: CVPixelBuffer
    ) {
        isPausedForLanding = true
        let frozenFrame = cameraController.captureSnapshot()

        DispatchQueue.main.async {
            self.tracks = tracks
            self.primaryTrack = tracks.first(where: { $0.id == landing.trackID })
            self.landingCandidate = landing
            self.diagnostics = diagnostics
            self.frozenFrame = frozenFrame
            self.phase = .verifying
        }

        let result = classifier.classify(region: landing.boundingBox, in: pixelBuffer)
        DispatchQueue.main.async {
            self.classificationResult = result
            self.phase = result.isMosquito ? .confirmed : .landingLocated
            if result.isMosquito {
                self.hapticsEngine.mosquitoConfirmed()
            } else {
                self.hapticsEngine.targetEngaging()
            }
        }
    }

    private func resetPublishedState() {
        detector.reset()
        tracks = []
        primaryTrack = nil
        landingCandidate = nil
        classificationResult = nil
        diagnostics = StationaryDetectorDiagnostics()
        frozenFrame = nil
        errorMessage = nil
        elapsedTime = "00:00"
        isPausedForLanding = false
        hasLockedCapture = false
        stableSince = nil
        wasDeviceMoving = false
    }

    private func startTimer() {
        stopTimer()
        sessionTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self, let sessionStartedAt = self.sessionStartedAt else { return }
            let elapsed = Int(Date().timeIntervalSince(sessionStartedAt))
            self.elapsedTime = String(format: "%02d:%02d", elapsed / 60, elapsed % 60)
        }
    }

    private func stopTimer() {
        sessionTimer?.invalidate()
        sessionTimer = nil
        sessionStartedAt = nil
    }

    private func saveLandingReview(label: String) {
        guard let frozenFrame,
              let imageData = frozenFrame.jpegData(compressionQuality: 0.92),
              let landingCandidate else {
            return
        }

        let classificationResult = classificationResult
        DispatchQueue.global(qos: .utility).async {
            let fileManager = FileManager.default
            guard let documents = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first else {
                return
            }
            let directory = documents
                .appendingPathComponent("MosquitoFinderReview", isDirectory: true)
                .appendingPathComponent("stationary_flight", isDirectory: true)
            let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")

            do {
                try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
                try imageData.write(to: directory.appendingPathComponent("\(stamp).jpg"), options: .atomic)
                let metadata: [String: Any] = [
                    "label": label,
                    "created_at": stamp,
                    "flight_confidence": Double(landingCandidate.confidence),
                    "stage2_confidence": Double(classificationResult?.confidence ?? 0),
                    "landing_rect": [
                        "x": Double(landingCandidate.boundingBox.origin.x),
                        "y": Double(landingCandidate.boundingBox.origin.y),
                        "width": Double(landingCandidate.boundingBox.width),
                        "height": Double(landingCandidate.boundingBox.height)
                    ]
                ]
                let metadataData = try JSONSerialization.data(withJSONObject: metadata, options: [.prettyPrinted, .sortedKeys])
                try metadataData.write(to: directory.appendingPathComponent("\(stamp).json"), options: .atomic)
            } catch {
                print("保存固定监测复核样本失败: \(error)")
            }
        }
    }
}
