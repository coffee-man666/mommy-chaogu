import SwiftUI

struct PortfolioView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 16) {
                AppCard {
                    Text("持仓市值").font(.caption).foregroundStyle(palette.secondary)
                    Text((store.portfolio.marketValue ?? store.portfolio.totalCost).moneyText).font(.system(size: 34, weight: .bold, design: .rounded)).padding(.vertical, 4)
                    HStack { Text("累计浮盈亏"); Spacer(); Text((store.portfolio.pnl ?? 0).moneyText).foregroundStyle(palette.marketColor(store.portfolio.pnl ?? 0)); if let pct = store.portfolio.pnlPct { ChangeLabel(value: pct) } }
                }
                Button { store.tab = 3; Task { await store.send("复盘我的全部持仓，按风险优先级告诉我今天最需要处理什么") } } label: {
                    Label("让 AI 深度复盘持仓", systemImage: "sparkles").frame(maxWidth: .infinity).padding(14)
                }.buttonStyle(.borderedProminent)
                SectionHeader(title: "全部持仓")
                if store.portfolio.positions.isEmpty { EmptyState(icon: "briefcase", title: "还没有持仓", detail: "在 Web 或 CLI 录入后会自动同步到这里") }
                ForEach(store.portfolio.positions) { position in
                    AppCard {
                        HStack { VStack(alignment: .leading) { Text(position.name ?? position.code).font(.headline); Text(position.code + " · \(position.shares) 股").font(.caption).foregroundStyle(palette.secondary) }; Spacer(); if let pct = position.pnlPct { ChangeLabel(value: pct) } }
                        Divider().padding(.vertical, 10)
                        HStack { value("成本", String(format: "%.2f", position.avgCost)); Spacer(); value("现价", position.currentPrice.map { String(format: "%.2f", $0) } ?? "—"); Spacer(); value("盈亏", position.pnl?.moneyText ?? "—") }
                    }
                }
            }.padding(16)
        }.background(palette.background).navigationTitle("持仓分析").refreshable { await store.loadPortfolio() }
    }
    private func value(_ name: String, _ value: String) -> some View { VStack(alignment: .leading, spacing: 3) { Text(name).font(.caption2).foregroundStyle(palette.secondary); Text(value).font(.callout.bold()) } }
}
