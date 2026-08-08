import Charts
import SwiftUI

struct MarketView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        List {
            if let quote = store.selectedQuote {
                Section {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading) { Text(quote.name).font(.title2.bold()); Text(quote.code).foregroundStyle(palette.secondary) }
                            Spacer(); VStack(alignment: .trailing) { Text(String(format: "%.2f", quote.price)).font(.title.bold()); ChangeLabel(value: quote.changePct) }
                        }
                        if store.bars.isEmpty {
                            Button("载入 K 线") { Task { await store.selectQuote(quote) } }.buttonStyle(.borderedProminent)
                        } else {
                            Chart(store.bars) { bar in
                                LineMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close)).foregroundStyle(palette.accent)
                                AreaMark(x: .value("时间", bar.timestamp), y: .value("收盘", bar.close)).foregroundStyle(LinearGradient(colors: [palette.accent.opacity(0.3), .clear], startPoint: .top, endPoint: .bottom))
                            }.frame(height: 190).chartXAxis(.hidden).chartYAxis { AxisMarks(position: .trailing) }
                        }
                    }.padding(.vertical, 8)
                }
            }
            Section("自选行情") {
                ForEach(store.quotes) { quote in
                    Button { Task { await store.selectQuote(quote) } } label: { QuoteRow(quote: quote) }.buttonStyle(.plain)
                }
            }
        }.scrollContentBackground(.hidden).background(palette.background).navigationTitle("市场").refreshable { await store.loadMarket() }
    }
}
