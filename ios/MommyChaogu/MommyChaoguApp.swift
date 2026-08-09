import SwiftUI

@main
struct MommyChaoguApp: App {
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(store)
                .environment(\.appPalette, store.theme.palette)
                .preferredColorScheme(store.theme.colorScheme)
                .tint(store.theme.palette.accent)
                .task { await store.bootstrap() }
        }
    }
}
