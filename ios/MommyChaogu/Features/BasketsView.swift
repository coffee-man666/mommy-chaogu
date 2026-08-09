import Charts
import SwiftUI

struct BasketsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                Text("把一个逻辑，装进一个篮子")
                    .font(.subheadline)
                    .foregroundStyle(palette.secondary)

                LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 10) {
                    ForEach(store.baskets.filter { !$0.hidden }) { basket in
                        NavigationLink { BasketDetailView(basket: basket) } label: {
                            BasketCatalogCard(basket: basket)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding(16)
        }
        .background(palette.background)
        .navigationTitle("股票篮子")
        .refreshable { await store.loadBaskets() }
    }
}

private struct BasketCatalogCard: View {
    @Environment(\.appPalette) private var palette
    let basket: Basket

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Image(systemName: basket.kind == "theme" ? "circle.hexagongrid.fill" : "square.stack.3d.up.fill")
                    .font(.title3)
                    .foregroundStyle(palette.accent)
                    .frame(width: 34, height: 34)
                    .background(palette.elevated, in: RoundedRectangle(cornerRadius: 10))
                Spacer()
                Text("\(basket.totalStocks) 只")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(palette.secondary)
            }
            Text(basket.name)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(palette.text)
                .lineLimit(2)
            Text(basket.members.prefix(2).map(\.name).joined(separator: " · "))
                .font(.caption2)
                .foregroundStyle(palette.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 124, alignment: .topLeading)
        .padding(13)
        .background(palette.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

struct BasketDetailView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    let basket: Basket
    @State private var detail: BasketDetail?
    @State private var loadError: String?

    private var members: [BasketMember] {
        detail.map(\.members) ?? basket.members
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 13) {
                basketSummary

                Button {
                    store.tab = 3
                    Task { await store.send("分析股票篮子「\(basket.name)」的机会、风险和当前强弱") }
                } label: {
                    Label("交给 AI 分析这个篮子", systemImage: "sparkles")
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                }
                .buttonStyle(.borderedProminent)

                HStack(alignment: .firstTextBaseline) {
                    SectionHeader(title: "成分股", action: "\(members.count) 只")
                    Spacer(minLength: 0)
                }

                if members.isEmpty {
                    EmptyState(icon: "square.grid.2x2", title: "这个篮子还没有成分股", detail: "可以先在服务端添加自选股或主题成员")
                } else {
                    LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 10) {
                        ForEach(members) { member in
                            NavigationLink { StockDetailView(member: member) } label: {
                                BasketMemberCard(member: member)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                if detail == nil, !basket.members.isEmpty {
                    HStack(spacing: 7) {
                        ProgressView().controlSize(.small)
                        Text("实时表现同步中，先展示目录成员")
                            .font(.caption)
                            .foregroundStyle(palette.secondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.top, 2)
                }

                if let loadError {
                    Label(loadError, systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(16)
        }
        .background(palette.background)
        .navigationTitle(basket.name)
        .task { await loadDetail() }
    }

    private var basketSummary: some View {
        AppCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .top, spacing: 11) {
                    Image(systemName: basket.kind == "theme" ? "circle.hexagongrid.fill" : "square.stack.3d.up.fill")
                        .font(.title2)
                        .foregroundStyle(palette.accent)
                        .frame(width: 42, height: 42)
                        .background(palette.elevated, in: RoundedRectangle(cornerRadius: 13))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(basket.name).font(.headline)
                        Text(detail?.description ?? basket.description)
                            .font(.caption)
                            .foregroundStyle(palette.secondary)
                            .lineLimit(3)
                    }
                    Spacer(minLength: 0)
                }

                HStack(spacing: 0) {
                    BasketMetric(title: "成分股", value: "\(basket.totalStocks) 只")
                    Spacer()
                    if let change = detail?.changePct {
                        VStack(alignment: .trailing, spacing: 3) {
                            Text("篮子涨跌").font(.caption2).foregroundStyle(palette.secondary)
                            ChangeLabel(value: change)
                        }
                    } else {
                        BasketMetric(title: "实时表现", value: detail == nil ? "同步中" : "暂无数据")
                    }
                    Spacer()
                    BasketStatusPill(status: detail?.status ?? "loading")
                }

                if let message = detail?.message {
                    Label(message, systemImage: detail?.status == "stale" ? "clock" : "info.circle")
                        .font(.caption2)
                        .foregroundStyle(palette.secondary)
                }
            }
        }
    }

    private func loadDetail() async {
        do {
            detail = try await store.basketDetail(basket)
        } catch {
            loadError = error.localizedDescription
        }
    }
}

private struct BasketMetric: View {
    @Environment(\.appPalette) private var palette
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption2).foregroundStyle(palette.secondary)
            Text(value).font(.callout.bold())
        }
    }
}

private struct BasketStatusPill: View {
    @Environment(\.appPalette) private var palette
    let status: String

    var body: some View {
        Text(label)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(color.opacity(0.12), in: Capsule())
    }

    private var label: String {
        switch status {
        case "ok": "行情正常"
        case "stale": "行情较旧"
        case "unavailable": "暂无行情"
        default: "同步中"
        }
    }

    private var color: Color {
        switch status {
        case "ok": palette.negative
        case "stale": .orange
        case "unavailable": palette.secondary
        default: palette.accent
        }
    }
}

private struct BasketMemberCard: View {
    @Environment(\.appPalette) private var palette
    let member: BasketMember

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Text(String(member.name.prefix(1)))
                    .font(.caption.bold())
                    .frame(width: 27, height: 27)
                    .foregroundStyle(palette.accent)
                    .background(palette.accent.opacity(0.14), in: Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text(member.name).font(.subheadline.weight(.semibold)).lineLimit(1)
                    Text(member.code).font(.caption2).foregroundStyle(palette.secondary)
                }
                Spacer(minLength: 3)
                Text(weightText)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(palette.secondary)
            }

            if !member.note.isEmpty {
                Text(member.note)
                    .font(.caption2)
                    .foregroundStyle(palette.secondary)
                    .lineLimit(1)
            }

            HStack(alignment: .firstTextBaseline) {
                if let price = member.price {
                    Text(String(format: "¥%.2f", price))
                        .font(.caption.weight(.semibold))
                } else {
                    Text("暂无行情").font(.caption2).foregroundStyle(palette.secondary)
                }
                Spacer(minLength: 4)
                if let change = member.changePct {
                    ChangeLabel(value: change).font(.caption)
                } else {
                    Text("未同步").font(.caption2).foregroundStyle(palette.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 104, alignment: .topLeading)
        .padding(12)
        .background(palette.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private var weightText: String {
        guard let weight = member.weight else { return "等权" }
        return String(format: "%.1f%%", weight)
    }
}

struct StockDetailView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    let member: BasketMember
    @State private var quote: Quote?
    @State private var bars: [Bar] = []
    @State private var errorMessage: String?
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 13) {
                AppCard {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(quote?.name ?? member.name).font(.title2.bold())
                                Text(member.code).font(.caption).foregroundStyle(palette.secondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 3) {
                                if let price = quote?.price ?? member.price {
                                    Text(String(format: "¥%.2f", price)).font(.title.bold())
                                } else {
                                    Text("暂无价格").font(.headline).foregroundStyle(palette.secondary)
                                }
                                if let change = quote?.changePct ?? member.changePct {
                                    ChangeLabel(value: change)
                                }
                            }
                        }
                        if !member.note.isEmpty {
                            Label(member.note, systemImage: "tag")
                                .font(.caption)
                                .foregroundStyle(palette.secondary)
                        }
                        if let quote {
                            HStack(spacing: 0) {
                                QuoteMetric(title: "成交量", value: volumeText(quote.volume))
                                Spacer()
                                QuoteMetric(title: "开盘", value: String(format: "¥%.2f", quote.price))
                                Spacer()
                                QuoteMetric(title: "状态", value: "已同步")
                            }
                        }
                    }
                }

                if let errorMessage {
                    AppCard {
                        Label(errorMessage, systemImage: "exclamationmark.triangle")
                            .font(.subheadline)
                            .foregroundStyle(.orange)
                    }
                }

                SectionHeader(title: "走势", action: bars.isEmpty ? nil : "60 日")
                if bars.isEmpty {
                    if isLoading {
                        ProgressView("正在加载行情")
                            .frame(maxWidth: .infinity)
                            .padding(36)
                    } else {
                        EmptyState(icon: "chart.xyaxis.line", title: "暂无 K 线", detail: "行情服务返回后，这里会显示走势")
                    }
                } else {
                    AppCard {
                        Chart(bars) { bar in
                            LineMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close))
                                .foregroundStyle(palette.accent)
                            AreaMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close))
                                .foregroundStyle(LinearGradient(colors: [palette.accent.opacity(0.28), .clear], startPoint: .top, endPoint: .bottom))
                        }
                        .frame(height: 190)
                        .chartXAxis(.hidden)
                    }
                }
            }
            .padding(16)
        }
        .background(palette.background)
        .navigationTitle(member.name)
        .task { await load() }
    }

    private func load() async {
        isLoading = true
        errorMessage = nil
        switch store.marketState {
        case let .empty(message), let .failed(message):
            errorMessage = message
            isLoading = false
            return
        default:
            break
        }
        do {
            let loadedQuote = try await store.loadQuote(member.code)
            quote = loadedQuote
            store.selectedQuote = loadedQuote
            bars = try await store.loadBars(member.code)
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func volumeText(_ value: Int) -> String {
        if value >= 100_000_000 { return String(format: "%.1f 亿", Double(value) / 100_000_000) }
        if value >= 10_000 { return String(format: "%.1f 万", Double(value) / 10_000) }
        return "\(value)"
    }
}

private struct QuoteMetric: View {
    @Environment(\.appPalette) private var palette
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption2).foregroundStyle(palette.secondary)
            Text(value).font(.caption.weight(.semibold))
        }
    }
}
