//
//  Mosquito_finderApp.swift
//  Mosquito-finder
//
//  Created by NSaviour on 2025/12/18.
//

import SwiftUI
import CoreData

@main
struct Mosquito_finderApp: App {
    let persistenceController = PersistenceController.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(\.managedObjectContext, persistenceController.container.viewContext)
        }
    }
}
