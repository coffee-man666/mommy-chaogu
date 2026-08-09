import Charts
import SwiftUI

struct MarketView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 13) {
                MarketStatusCard(state: store.marketState, session: marketSession)

                if let quote = store.selectedQuote {
                    SelectedQuoteCard(quote: quote, bars: store.bars) {
                        Task { await store.selectQuote(quote) }
                    }
                }

                SectionHeader(title: "自选行情", action: "\(store.quotes.count) 只")
                if store.quotes.isEmpty {
                    MarketEmptyState(state: store.marketState, session: marketSession)
                } else {
                    AppCard {
                        ForEach(Array(store.quotes.enumerated()), id: \.element.id) { index, quote in
                            Button { Task { await store.selectQuote(quote) } } label: {
                                QuoteRow(quote: quote)
                            }
                            .buttonStyle(.plain)
                            if index < store.quotes.count - 1 {
                                Divider().padding(.leading, 46)
                            }
                        }
                    }
                }
            }
            .padding(16)
        }
        .background(palette.background)
        .navigationTitle("市场")
        .refreshable { await store.loadMarket() }
    }

    private var marketSession: String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai") ?? .current
        let now = Date()
        let weekday = calendar.component(.weekday, from: now)
        if weekday == 1 || weekday == 7 { return "A 股：今日休市" }
        let hour = calendar.component(.hour, from: now)
        let minute = calendar.component(.minute, from: now)
        let totalMinutes = hour * 60 + minute
        if (570...690).contains(totalMinutes) || (780...900).contains(totalMinutes) { return "A 股：交易中" }
        return "A 股：非交易时段"
    }
}

private struct MarketStatusCard: View {
    @Environment(\.appPalette) private var palette
    let state: MarketDataState
    let session: String

    var body: some View {
        AppCard {
            HStack(spacing: 11) {
                Image(systemName: icon)
                    .font(.headline)
                    .foregroundStyle(color)
                    .frame(width: 34, height: 34)
                    .background(color.opacity(0.13), in: Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.subheadline.weight(.semibold))
                    Text(detail).font(.caption).foregroundStyle(palette.secondary).lineLimit(2)
                }
                Spacer(minLength: 8)
                Text(session)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(palette.secondary)
                    .multilineTextAlignment(.trailing)
            }
        }
    }

    private var title: String {
        switch state {
        case .idle: "等待行情服务"
        case .loading: "正在同步行情"
        case .ready: "行情服务正常"
        case .empty: "暂无行情快照"
        case .failed: "行情服务不可用"
        }
    }

    private var detail: String {
        switch state {
        case .idle: "下拉刷新以检查服务状态"
        case .loading: "正在读取自选股的最新数据"
        case .ready: "自选股行情已同步"
        case let .empty(message), let .failed(message): message
        }
    }

    private var icon: String {
        switch state {
        case .ready: "checkmark.circle.fill"
        case .failed: "wifi.exclamationmark"
        case .empty: "moon.zzz.fill"
        default: "arrow.triangle.2.circlepath"
        }
    }

    private var color: Color {
        switch state {
        case .ready: palette.negative
        case .failed: .orange
        case .empty: palette.secondary
        default: palette.accent
        }
    }
}

private struct MarketEmptyState: View {
    @Environment(\.appPalette) private var palette
    let state: MarketDataState
    let session: String

    var body: some View {
        AppCard {
            VStack(spacing: 10) {
                Image(systemName: icon).font(.system(size: 30)).foregroundStyle(palette.accent)
                Text(title).font(.headline)
                Text(detail).font(.subheadline).foregroundStyle(palette.secondary).multilineTextAlignment(.center)
                Text(session).font(.caption.weight(.semibold)).foregroundStyle(palette.secondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 18)
        }
    }

    private var title: String {
        switch state {
        case .loading: "正在等待行情"
        case .failed: "暂时拿不到行情"
        case .empty: "当前没有可展示的行情"
        default: "还没有自选行情"
        }
    }

    private var detail: String {
        switch state {
        case .failed: "请检查服务地址或后端是否运行。连接成功后，下拉刷新即可重试。"
        case .empty: "可能是休市、还没有添加自选股，或数据源尚未生成首份快照。"
        default: "添加自选股后，它们会在这里显示价格、涨跌和成交信息。"
        }
    }

    private var icon: String {
        switch state {
        case .failed: "wifi.exclamationmark"
        case .empty: "chart.line.flattrend.xyaxis"
        default: "chart.xyaxis.line"
        }
    }
}

private struct SelectedQuoteCard: View {
    @Environment(\.appPalette) private var palette
    let quote: Quote
    let bars: [Bar]
    let reload: () -> Void

    var body: some View {
        AppCard {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(quote.name).font(.title2.bold())
                        Text(quote.code).font(.caption).foregroundStyle(palette.secondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 3) {
                        Text(String(format: "¥%.2f", quote.price)).font(.title.bold())
                        ChangeLabel(value: quote.changePct)
                    }
                }
                if bars.isEmpty {
                    Button("载入 K 线", action: reload).buttonStyle(.borderedProminent)
                } else {
                    Chart(bars) { bar in
                        LineMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close))
                            .foregroundStyle(palette.accent)
                        AreaMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close))
                            .foregroundStyle(LinearGradient(colors: [palette.accent.opacity(0.28), .clear], startPoint: .top, endPoint: .bottom))
                    }
                    .frame(height: 170)
                    .chartXAxis(.hidden)
                }
            }
        }
    }
}
