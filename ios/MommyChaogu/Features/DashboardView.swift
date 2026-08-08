import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(greeting).font(.subheadline).foregroundStyle(palette.secondary)
                        Text("今天，稳稳地看清楚").font(.largeTitle.bold())
                    }
                    Spacer()
                    ConnectionBadge(state: store.connection)
                }

                Button { store.tab = 3 } label: {
                    AppCard {
                        HStack(spacing: 14) {
                            ZStack { Circle().fill(palette.accent.opacity(0.16)).frame(width: 48, height: 48); Image(systemName: "waveform.and.sparkles").foregroundStyle(palette.accent) }
                            VStack(alignment: .leading, spacing: 4) {
                                Text("问问 AI 今天该看什么").font(.headline).foregroundStyle(palette.text)
                                Text("持仓、资金流、新闻与记忆一起分析").font(.caption).foregroundStyle(palette.secondary)
                            }
                            Spacer(); Image(systemName: "arrow.right").foregroundStyle(palette.accent)
                        }
                    }
                }.buttonStyle(.plain)

                SectionHeader(title: "持仓温度")
                AppCard {
                    HStack(alignment: .bottom) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("总资产").font(.caption).foregroundStyle(palette.secondary)
                            Text((store.portfolio.marketValue ?? store.portfolio.totalCost).moneyText).font(.system(size: 30, weight: .bold, design: .rounded))
                        }
                        Spacer()
                        if let pct = store.portfolio.pnlPct { ChangeLabel(value: pct) }
                    }
                    Divider().padding(.vertical, 12)
                    HStack {
                        metric("持仓", "\(store.portfolio.count) 只")
                        Spacer(); metric("浮动盈亏", (store.portfolio.pnl ?? 0).moneyText)
                        Spacer(); metric("今日信号", "—")
                    }
                }

                SectionHeader(title: "自选快照", action: "共 \(store.quotes.count) 只")
                if store.quotes.isEmpty { EmptyState(icon: "chart.line.uptrend.xyaxis", title: "等待第一份行情", detail: "连接服务后，自选股会出现在这里") }
                else {
                    AppCard {
                        ForEach(Array(store.quotes.prefix(5).enumerated()), id: \.element.id) { index, quote in
                            QuoteRow(quote: quote)
                            if index < min(store.quotes.count, 5) - 1 { Divider().padding(.leading, 42) }
                        }
                    }
                }

                SectionHeader(title: "AI 记住的判断", action: "\(store.predictions.count) 条")
                if let prediction = store.predictions.first {
                    AppCard {
                        Label(prediction.code + " · " + prediction.status, systemImage: "brain.head.profile").font(.headline)
                        Text(prediction.reasoning ?? "这条判断正在等待市场验证。")
                            .font(.subheadline).foregroundStyle(palette.secondary).padding(.top, 8)
                    }
                } else { EmptyState(icon: "brain", title: "记忆正在生长", detail: "和 AI 聊过的投资判断会沉淀在这里") }
            }.padding(16)
        }.background(palette.background).navigationBarHidden(true).refreshable { await store.bootstrap() }
    }

    private var greeting: String { Calendar.current.component(.hour, from: .now) < 12 ? "早上好" : "你好" }
    private func metric(_ title: String, _ value: String) -> some View { VStack(alignment: .leading, spacing: 3) { Text(title).font(.caption2).foregroundStyle(palette.secondary); Text(value).font(.callout.bold()) } }
}
struct ConnectionBadge: View {
    @Environment(\.appPalette) private var palette
    let state: ConnectionState
    var body: some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(text).font(.caption2.weight(.semibold))
        }.padding(.horizontal, 10).padding(.vertical, 7).background(palette.surface, in: Capsule())
    }
    private var color: Color { if case .online = state { return .green }; if case .failed = state { return .orange }; return palette.secondary }
    private var text: String { if case .online = state { return "已连接" }; if case .loading = state { return "同步中" }; if case .failed = state { return "需检查" }; return "未连接" }
}

struct QuoteRow: View {
    @Environment(\.appPalette) private var palette
    let quote: Quote
    var body: some View {
        HStack(spacing: 12) {
            Text(String(quote.name.prefix(1))).font(.headline).frame(width: 34, height: 34).background(palette.elevated, in: Circle())
            VStack(alignment: .leading, spacing: 2) { Text(quote.name).font(.callout.bold()); Text(quote.code).font(.caption2).foregroundStyle(palette.secondary) }
            Spacer(); VStack(alignment: .trailing, spacing: 2) { Text(String(format: "%.2f", quote.price)).font(.system(.callout, design: .rounded, weight: .semibold)); ChangeLabel(value: quote.changePct).font(.caption) }
        }.padding(.vertical, 8)
    }
}
