import Foundation

extension KeyedDecodingContainer {
    func flexibleDouble(forKey key: Key) throws -> Double {
        if let value = try? decode(Double.self, forKey: key) { return value }
        if let value = try? decode(String.self, forKey: key), let number = Double(value) { return number }
        return 0
    }

    func optionalFlexibleDouble(forKey key: Key) -> Double? {
        if let value = try? decode(Double.self, forKey: key) { return value }
        if let value = try? decode(String.self, forKey: key), let number = Double(value) { return number }
        return nil
    }
}

struct Quote: Decodable, Identifiable {
    let code: String
    let name: String
    let price: Double
    let changePct: Double
    let volume: Int
    let timestamp: String
    var id: String { code }

    enum CodingKeys: String, CodingKey { case code, name, price, volume, timestamp; case changePct = "change_pct" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        code = try c.decode(String.self, forKey: .code)
        name = try c.decode(String.self, forKey: .name)
        price = try c.flexibleDouble(forKey: .price)
        changePct = try c.flexibleDouble(forKey: .changePct)
        volume = (try? c.decode(Int.self, forKey: .volume)) ?? 0
        timestamp = (try? c.decode(String.self, forKey: .timestamp)) ?? ""
    }
}

struct QuoteSnapshot: Decodable {
    let quotes: [Quote]
    let nUp: Int
    let nDown: Int
    enum CodingKeys: String, CodingKey { case quotes; case nUp = "n_up"; case nDown = "n_down" }
}

struct Bar: Decodable, Identifiable {
    let timestamp: String
    let open, high, low, close: Double
    var id: String { timestamp }
    enum CodingKeys: String, CodingKey { case timestamp, open, high, low, close }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        timestamp = try c.decode(String.self, forKey: .timestamp)
        open = try c.flexibleDouble(forKey: .open); high = try c.flexibleDouble(forKey: .high)
        low = try c.flexibleDouble(forKey: .low); close = try c.flexibleDouble(forKey: .close)
    }
}

struct Position: Decodable, Identifiable {
    let id: Int
    let code: String
    let name: String?
    let avgCost, totalCost: Double
    let shares: Int
    let currentPrice, marketValue, pnl, pnlPct: Double?
    enum CodingKeys: String, CodingKey { case id, code, name, shares; case avgCost = "avg_cost"; case totalCost = "total_cost"; case currentPrice = "current_price"; case marketValue = "market_value"; case pnl = "unrealized_pnl"; case pnlPct = "unrealized_pnl_pct" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int.self, forKey: .id); code = try c.decode(String.self, forKey: .code)
        name = try? c.decodeIfPresent(String.self, forKey: .name); shares = try c.decode(Int.self, forKey: .shares)
        avgCost = try c.flexibleDouble(forKey: .avgCost); totalCost = try c.flexibleDouble(forKey: .totalCost)
        currentPrice = c.optionalFlexibleDouble(forKey: .currentPrice); marketValue = c.optionalFlexibleDouble(forKey: .marketValue)
        pnl = c.optionalFlexibleDouble(forKey: .pnl); pnlPct = c.optionalFlexibleDouble(forKey: .pnlPct)
    }
}

struct PortfolioSummary: Decodable {
    let positions: [Position]
    let totalCost: Double
    let marketValue, pnl, pnlPct: Double?
    let count: Int
    enum CodingKeys: String, CodingKey { case positions; case totalCost = "total_cost"; case marketValue = "total_market_value"; case pnl = "total_unrealized_pnl"; case pnlPct = "total_unrealized_pnl_pct"; case count = "n_positions" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        positions = try c.decode([Position].self, forKey: .positions); totalCost = try c.flexibleDouble(forKey: .totalCost)
        marketValue = c.optionalFlexibleDouble(forKey: .marketValue); pnl = c.optionalFlexibleDouble(forKey: .pnl)
        pnlPct = c.optionalFlexibleDouble(forKey: .pnlPct); count = try c.decode(Int.self, forKey: .count)
    }
    static let empty = PortfolioSummary(positions: [], totalCost: 0, marketValue: nil, pnl: nil, pnlPct: nil, count: 0)
    private init(positions: [Position], totalCost: Double, marketValue: Double?, pnl: Double?, pnlPct: Double?, count: Int) {
        self.positions = positions; self.totalCost = totalCost; self.marketValue = marketValue; self.pnl = pnl; self.pnlPct = pnlPct; self.count = count
    }
}

struct Basket: Decodable, Identifiable {
    let id, name, kind: String
    let description: String
    let totalStocks: Int
    let followed, hidden: Bool
    let reason: String
    enum CodingKeys: String, CodingKey { case id, name, kind, description, followed, hidden, reason; case totalStocks = "total_stocks" }
}

struct BasketMember: Decodable, Identifiable {
    let code, name: String
    let weight: Double?
    var id: String { code }
    enum CodingKeys: String, CodingKey { case code, name, weight }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        code = try c.decode(String.self, forKey: .code); name = try c.decode(String.self, forKey: .name)
        weight = c.optionalFlexibleDouble(forKey: .weight)
    }
}

struct BasketDetail: Decodable {
    let id, name, kind, description: String
    let members: [BasketMember]
    let changePct: Double?
    enum CodingKeys: String, CodingKey { case id, name, kind, description, members; case changePct = "change_pct" }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id); name = try c.decode(String.self, forKey: .name)
        kind = try c.decode(String.self, forKey: .kind); description = (try? c.decode(String.self, forKey: .description)) ?? ""
        members = try c.decode([BasketMember].self, forKey: .members); changePct = c.optionalFlexibleDouble(forKey: .changePct)
    }
}

struct ChatMessage: Identifiable, Codable, Equatable {
    enum Role: String, Codable { case user, assistant, system }
    let id: UUID
    let role: Role
    var content: String
    let createdAt: Date
    var tools: [String]
    init(id: UUID = UUID(), role: Role, content: String, createdAt: Date = .now, tools: [String] = []) {
        self.id = id; self.role = role; self.content = content; self.createdAt = createdAt; self.tools = tools
    }
}

struct Conversation: Identifiable, Codable, Equatable {
    let id: String
    var title: String
    var updatedAt: Date
    var preview: String
    init(id: String = "ios-" + UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(20), title: String = "新对话", updatedAt: Date = .now, preview: String = "") {
        self.id = id; self.title = title; self.updatedAt = updatedAt; self.preview = preview
    }
}

struct HistoryEnvelope: Decodable { let messages: [HistoryRow] }
struct HistoryRow: Decodable {
    let role, content: String
    let createdAt: String?
    enum CodingKeys: String, CodingKey { case role, content; case createdAt = "created_at" }
}

struct PredictionEnvelope: Decodable { let predictions: [Prediction] }
struct Prediction: Decodable, Identifiable {
    let id: Int
    let code: String
    let direction: String?
    let status: String
    let reasoning: String?
}

struct WSTicket: Decodable { let ticket: String }

enum VoiceProvider: String, CaseIterable, Codable, Identifiable {
    case system = "系统语音 + Agent"
    case minimax = "MiniMax 实时语音"

    var id: String { rawValue }
}

enum ConnectionState: Equatable { case idle, loading, online, failed(String) }
