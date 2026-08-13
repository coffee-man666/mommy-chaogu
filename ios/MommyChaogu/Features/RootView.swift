import SwiftUI

struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette

    var body: some View {
        TabView(selection: $store.tab) {
            NavigationStack { DashboardView() }.tabItem { Label("今日", systemImage: "sparkles") }.tag(0)
            NavigationStack { MarketView() }.tabItem { Label("市场", systemImage: "chart.xyaxis.line") }.tag(1)
            NavigationStack { BasketsView() }.tabItem { Label("篮子", systemImage: "square.grid.2x2") }.tag(2)
            NavigationStack { ConversationsView() }.tabItem { Label("AI", systemImage: "message.fill") }.tag(3)
            NavigationStack { ProfileView() }.tabItem { Label("我的", systemImage: "person.crop.circle") }.tag(4)
        }
        .background(palette.background)
        .alert("提示", isPresented: Binding(get: { store.toast != nil }, set: { if !$0 { store.toast = nil } })) {
            Button("知道了", role: .cancel) { store.toast = nil }
        } message: { Text(store.toast ?? "") }
    }
}
