//
//  HuntingStatsStore.swift
//  Mosquito-finder
//
//  Persistent hunting stats used by the Trophy page and session summaries.
//

import Foundation
import Combine

struct HuntSessionRecord: Identifiable, Codable {
    let id: UUID
    let startedAt: Date
    let endedAt: Date
    let duration: TimeInterval
    let confirmedMosquitoes: Int
    let suspectsFound: Int
    let bestConfidence: Float
    let modelModeRawValue: String

    var modelMode: RuntimeModelMode {
        RuntimeModelMode(rawValue: modelModeRawValue) ?? .coreMLStrict
    }
}

struct MosquitoHitRecord: Identifiable, Codable {
    let id: UUID
    let timestamp: Date
    let confidence: Float
    let modelModeRawValue: String

    var modelMode: RuntimeModelMode {
        RuntimeModelMode(rawValue: modelModeRawValue) ?? .coreMLStrict
    }
}

struct HuntingStatsSnapshot {
    let sessionCount: Int
    let totalMosquitoes: Int
    let totalSuspects: Int
    let totalDuration: TimeInterval
    let bestConfidence: Float

    static let empty = HuntingStatsSnapshot(
        sessionCount: 0,
        totalMosquitoes: 0,
        totalSuspects: 0,
        totalDuration: 0,
        bestConfidence: 0
    )
}

@MainActor
final class HuntingStatsStore: ObservableObject {
    static let shared = HuntingStatsStore()

    @Published private(set) var sessions: [HuntSessionRecord] = []
    @Published private(set) var hits: [MosquitoHitRecord] = []

    private let storageKey = "huntingStatsStore.v1"
    private let maxStoredSessions = 100
    private let maxStoredHits = 300
    private var activeSessionStart: Date?
    private var activeBestConfidence: Float = 0

    var snapshot: HuntingStatsSnapshot {
        guard !sessions.isEmpty || !hits.isEmpty else { return .empty }
        return HuntingStatsSnapshot(
            sessionCount: sessions.count,
            totalMosquitoes: hits.count,
            totalSuspects: sessions.reduce(0) { $0 + $1.suspectsFound },
            totalDuration: sessions.reduce(0) { $0 + $1.duration },
            bestConfidence: max(
                sessions.map(\.bestConfidence).max() ?? 0,
                hits.map(\.confidence).max() ?? 0
            )
        )
    }

    private init() {
        load()
    }

    func beginSession() {
        activeSessionStart = Date()
        activeBestConfidence = 0
    }

    func recordMosquito(confidence: Float, modelMode: RuntimeModelMode) {
        activeBestConfidence = max(activeBestConfidence, confidence)
        let hit = MosquitoHitRecord(
            id: UUID(),
            timestamp: Date(),
            confidence: confidence,
            modelModeRawValue: modelMode.rawValue
        )
        hits.insert(hit, at: 0)
        trimAndSave()
    }

    func endSession(suspectsFound: Int, confirmedMosquitoes: Int, modelMode: RuntimeModelMode) {
        let startedAt = activeSessionStart ?? Date()
        let endedAt = Date()
        let duration = max(0, endedAt.timeIntervalSince(startedAt))
        activeSessionStart = nil

        guard duration >= 2 || confirmedMosquitoes > 0 || suspectsFound > 0 else {
            activeBestConfidence = 0
            return
        }

        let record = HuntSessionRecord(
            id: UUID(),
            startedAt: startedAt,
            endedAt: endedAt,
            duration: duration,
            confirmedMosquitoes: confirmedMosquitoes,
            suspectsFound: suspectsFound,
            bestConfidence: activeBestConfidence,
            modelModeRawValue: modelMode.rawValue
        )
        sessions.insert(record, at: 0)
        activeBestConfidence = 0
        trimAndSave()
    }

    private func trimAndSave() {
        if sessions.count > maxStoredSessions {
            sessions = Array(sessions.prefix(maxStoredSessions))
        }
        if hits.count > maxStoredHits {
            hits = Array(hits.prefix(maxStoredHits))
        }
        save()
    }

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: storageKey) else { return }
        do {
            let payload = try JSONDecoder().decode(Payload.self, from: data)
            sessions = payload.sessions
            hits = payload.hits
        } catch {
            sessions = []
            hits = []
        }
    }

    private func save() {
        let payload = Payload(sessions: sessions, hits: hits)
        guard let data = try? JSONEncoder().encode(payload) else { return }
        UserDefaults.standard.set(data, forKey: storageKey)
    }

    private struct Payload: Codable {
        let sessions: [HuntSessionRecord]
        let hits: [MosquitoHitRecord]
    }
}
