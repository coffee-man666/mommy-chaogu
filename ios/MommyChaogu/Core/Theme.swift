import SwiftUI

enum AppTheme: String, CaseIterable, Codable, Identifiable {
    case midnight, cream, mint, neon

    var id: String { rawValue }
    var title: String {
        switch self {
        case .midnight: "深夜研究所"
        case .cream: "奶油拿铁"
        case .mint: "薄荷清晨"
        case .neon: "霓虹交易台"
        }
    }
    var subtitle: String {
        switch self {
        case .midnight: "克制、沉浸、专业"
        case .cream: "温柔、轻盈、治愈"
        case .mint: "清爽、安静、耐看"
        case .neon: "醒目、高对比、行动派"
        }
    }
    var colorScheme: ColorScheme {
        switch self { case .midnight, .neon: .dark; case .cream, .mint: .light }
    }
    var palette: AppPalette {
        switch self {
        case .midnight:
            AppPalette(background: Color(hex: 0x0B0D12), surface: Color(hex: 0x151923), elevated: Color(hex: 0x202635), text: .white, secondary: Color(hex: 0x9EA8BB), accent: Color(hex: 0x9B8CFF), positive: Color(hex: 0xFF625F), negative: Color(hex: 0x38C98A))
        case .cream:
            AppPalette(background: Color(hex: 0xFFF8EE), surface: Color(hex: 0xFFFDF9), elevated: Color(hex: 0xF5E9D8), text: Color(hex: 0x352A26), secondary: Color(hex: 0x8A7770), accent: Color(hex: 0xE4778E), positive: Color(hex: 0xE34D59), negative: Color(hex: 0x2E9C70))
        case .mint:
            AppPalette(background: Color(hex: 0xEFF8F5), surface: .white, elevated: Color(hex: 0xDCEFE8), text: Color(hex: 0x19352F), secondary: Color(hex: 0x68847D), accent: Color(hex: 0x168D78), positive: Color(hex: 0xE05260), negative: Color(hex: 0x168D78))
        case .neon:
            AppPalette(background: Color(hex: 0x080A0E), surface: Color(hex: 0x11151C), elevated: Color(hex: 0x1C2330), text: Color(hex: 0xF2F5FA), secondary: Color(hex: 0x8491A7), accent: Color(hex: 0xB6FF3B), positive: Color(hex: 0xFF4D67), negative: Color(hex: 0x20E3A2))
        }
    }
}
struct AppPalette {
    let background: Color
    let surface: Color
    let elevated: Color
    let text: Color
    let secondary: Color
    let accent: Color
    let positive: Color
    let negative: Color

    func marketColor(_ value: Double) -> Color { value >= 0 ? positive : negative }
}

private struct AppPaletteKey: EnvironmentKey {
    static let defaultValue = AppTheme.midnight.palette
}

extension EnvironmentValues {
    var appPalette: AppPalette {
        get { self[AppPaletteKey.self] }
        set { self[AppPaletteKey.self] = newValue }
    }
}

extension Color {
    init(hex: UInt, alpha: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xff) / 255,
                  green: Double((hex >> 08) & 0xff) / 255,
                  blue: Double((hex >> 00) & 0xff) / 255,
                  opacity: alpha)
    }
}
