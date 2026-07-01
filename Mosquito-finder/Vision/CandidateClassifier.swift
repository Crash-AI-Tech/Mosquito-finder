//
//  CandidateClassifier.swift
//  Mosquito-finder
//
//  Lightweight Stage 1 candidate scorer. This model does not confirm mosquitoes;
//  it only reranks candidate regions before tracking and guidance.
//

import Foundation
import CoreGraphics
import CoreML
import CoreVideo
import Vision

final class CandidateClassifier {
    private var request: VNCoreMLRequest?
    private var isModelLoaded = false

    func score(region: CGRect, in pixelBuffer: CVPixelBuffer) -> Float? {
        if !isModelLoaded {
            loadModel()
        }
        guard let request else { return nil }

        let frameWidth = CGFloat(CVPixelBufferGetWidth(pixelBuffer))
        let frameHeight = CGFloat(CVPixelBufferGetHeight(pixelBuffer))
        guard frameWidth > 0, frameHeight > 0 else { return nil }

        let roi = normalizedVisionROI(region: region, frameWidth: frameWidth, frameHeight: frameHeight)
        guard roi.width > 0.001, roi.height > 0.001 else { return nil }

        request.regionOfInterest = roi
        let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
        do {
            try handler.perform([request])
            return parseCandidateScore(from: request.results)
        } catch {
            print("Candidate classifier failed: \(error)")
            return nil
        }
    }

    private func loadModel() {
        defer { isModelLoaded = request != nil }

        guard let modelURL = Bundle.main.url(forResource: "CandidateSearchClassifier", withExtension: "mlmodelc") else {
            request = nil
            return
        }

        do {
            let config = MLModelConfiguration()
            config.computeUnits = .all
            let model = try MLModel(contentsOf: modelURL, configuration: config)
            let visionModel = try VNCoreMLModel(for: model)
            let request = VNCoreMLRequest(model: visionModel)
            request.imageCropAndScaleOption = .centerCrop
            self.request = request
        } catch {
            print("Candidate classifier load failed: \(error)")
            request = nil
        }
    }

    private func normalizedVisionROI(region: CGRect, frameWidth: CGFloat, frameHeight: CGFloat) -> CGRect {
        let clamped = region.intersection(CGRect(x: 0, y: 0, width: frameWidth, height: frameHeight))
        guard !clamped.isNull else { return .zero }

        let nx = clamped.origin.x / frameWidth
        let nw = clamped.width / frameWidth
        let nh = clamped.height / frameHeight
        let ny = 1.0 - (clamped.origin.y / frameHeight) - nh

        return CGRect(
            x: max(0, min(1 - nw, nx)),
            y: max(0, min(1 - nh, ny)),
            width: max(0.001, min(1, nw)),
            height: max(0.001, min(1, nh))
        )
    }

    private func parseCandidateScore(from results: [Any]?) -> Float? {
        guard let observations = results as? [VNClassificationObservation] else {
            return nil
        }

        var candidateScore: Float?
        for observation in observations {
            let label = observation.identifier
                .lowercased()
                .replacingOccurrences(of: "-", with: "_")
            if (label.contains("candidate") || label == "mosquito"),
               !label.contains("not"),
               !label.contains("negative"),
               !label.contains("background"),
               !label.contains("trap") {
                candidateScore = max(candidateScore ?? 0, observation.confidence)
            }
        }

        if let candidateScore {
            return candidateScore
        }

        // Some CoreML classifiers only return the winning label. Treat an
        // explicit background label as low candidate support.
        guard let top = observations.first else { return nil }
        let topLabel = top.identifier.lowercased()
        if topLabel.contains("not")
            || topLabel.contains("background")
            || topLabel.contains("negative")
            || topLabel.contains("trap") {
            return max(0, 1 - top.confidence)
        }
        return top.confidence
    }
}
