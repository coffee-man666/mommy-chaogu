import SwiftUI

struct AppCard<Content: View>: View {
    @Environment(\.appPalette) private var palette
    @ViewBuilder let content: Content
    var body: some View {
        content.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(palette.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}
struct SectionHeader: View {
    @Environment(\.appPalette) private var palette
    let title: String
    var action: String? = nil
    var body: some View {
        HStack {
            Text(title).font(.title3.bold())
            Spacer()
            if let action { Text(action).font(.caption.weight(.semibold)).foregroundStyle(palette.accent) }
        }
    }
}

struct ChangeLabel: View {
    @Environment(\.appPalette) private var palette
    let value: Double
    var body: some View {
        Text(String(format: "%@%.2f%%", value >= 0 ? "+" : "", value))
            .font(.system(.callout, design: .rounded, weight: .bold))
            .foregroundStyle(palette.marketColor(value))
    }
}

struct EmptyState: View {
    @Environment(\.appPalette) private var palette
    let icon: String
    let title: String
    let detail: String
    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: icon).font(.system(size: 32)).foregroundStyle(palette.accent)
            Text(title).font(.headline)
            Text(detail).font(.subheadline).foregroundStyle(palette.secondary).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(32)
    }
}

extension Double {
    var moneyText: String {
        let formatter = NumberFormatter(); formatter.numberStyle = .currency; formatter.currencySymbol = "¥"; formatter.maximumFractionDigits = 2
        return formatter.string(from: NSNumber(value: self)) ?? "¥--"
    }
}
