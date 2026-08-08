import SwiftUI

struct BasketsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                HStack { Text("把一个逻辑，装进一个篮子").font(.subheadline).foregroundStyle(palette.secondary); Spacer() }
                ForEach(store.baskets.filter { !$0.hidden }) { basket in
                    NavigationLink { BasketDetailView(basket: basket) } label: {
                        AppCard {
                            HStack {
                                Image(systemName: basket.kind == "theme" ? "circle.hexagongrid.fill" : "square.stack.3d.up.fill").font(.title2).foregroundStyle(palette.accent).frame(width: 42, height: 42).background(palette.elevated, in: RoundedRectangle(cornerRadius: 13))
                                VStack(alignment: .leading, spacing: 4) { Text(basket.name).font(.headline); Text(basket.description.isEmpty ? basket.reason : basket.description).font(.caption).foregroundStyle(palette.secondary).lineLimit(2) }
                                Spacer(); VStack(alignment: .trailing) { Text("\(basket.totalStocks)").font(.title3.bold()); Text("只股票").font(.caption2).foregroundStyle(palette.secondary) }
                            }
                        }
                    }.buttonStyle(.plain)
                }
            }.padding(16)
        }.background(palette.background).navigationTitle("股票篮子").refreshable { await store.loadBaskets() }
    }
}

struct BasketDetailView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    let basket: Basket
    @State private var detail: BasketDetail?
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 16) {
                AppCard {
                    Text(detail?.description ?? basket.description).foregroundStyle(palette.secondary)
                    if let change = detail?.changePct { HStack { Text("篮子涨跌").font(.headline); Spacer(); ChangeLabel(value: change) }.padding(.top, 12) }
                }
                Button { store.tab = 3; Task { await store.send("分析股票篮子「\(basket.name)」的机会、风险和当前强弱") } } label: { Label("交给 AI 分析这个篮子", systemImage: "sparkles").frame(maxWidth: .infinity).padding(12) }.buttonStyle(.borderedProminent)
                SectionHeader(title: "成分股")
                if let detail { ForEach(detail.members) { member in AppCard { HStack { VStack(alignment: .leading) { Text(member.name).font(.headline); Text(member.code).font(.caption).foregroundStyle(palette.secondary) }; Spacer(); Text(member.weight.map { String(format: "%.1f%%", $0) } ?? "等权").font(.callout.bold()) } } } }
                else { ProgressView().padding(40) }
            }.padding(16)
        }.background(palette.background).navigationTitle(basket.name).task { detail = try? await store.basketDetail(basket) }
    }
}
