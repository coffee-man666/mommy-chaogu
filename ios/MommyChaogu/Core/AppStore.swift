import Foundation
import SwiftUI

@MainActor
final class AppStore: ObservableObject {
    @Published var tab = 0
    @Published var theme: AppTheme
    @Published var voiceProvider: VoiceProvider
    @Published var configuration: ServerConfiguration
    @Published var connection: ConnectionState = .idle
    @Published var quotes: [Quote] = []
    @Published var bars: [Bar] = []
    @Published var selectedQuote: Quote?
    @Published var portfolio = PortfolioSummary.empty
    @Published var baskets: [Basket] = []
    @Published var predictions: [Prediction] = []
    @Published var conversations: [Conversation]
    @Published var activeConversationID: String
    @Published var messages: [ChatMessage] = []
    @Published var isResponding = false
    @Published var activeTools: [String] = []
    @Published var toast: String?

    private var client: APIClient
    private let defaults = UserDefaults.standard

    init() {
        let theme = AppTheme(rawValue: UserDefaults.standard.string(forKey: "appTheme") ?? "") ?? .midnight
        let voiceProvider = VoiceProvider(rawValue: UserDefaults.standard.string(forKey: "voiceProvider") ?? "") ?? .system
        let config = (try? UserDefaults.standard.data(forKey: "serverConfig").flatMap { try JSONDecoder().decode(ServerConfiguration.self, from: $0) }) ?? ServerConfiguration()
        var conversations = (try? UserDefaults.standard.data(forKey: "conversations").flatMap { try JSONDecoder().decode([Conversation].self, from: $0) }) ?? []
        if conversations.isEmpty { conversations = [Conversation(title: "开盘聊聊")] }
        self.theme = theme; self.voiceProvider = voiceProvider; self.configuration = config; self.conversations = conversations
        self.activeConversationID = conversations[0].id
        self.client = APIClient(configuration: config)
    }

    func bootstrap() async {
        connection = .loading
        await withTaskGroup(of: Void.self) { group in
            group.addTask { await self.loadMarket() }
            group.addTask { await self.loadPortfolio() }
            group.addTask { await self.loadBaskets() }
            group.addTask { await self.loadPredictions() }
        }
        await loadConversation(activeConversationID)
        if case .failed = connection {} else { connection = .online }
    }

    func saveSettings() {
        defaults.set(theme.rawValue, forKey: "appTheme")
        defaults.set(voiceProvider.rawValue, forKey: "voiceProvider")
        if let data = try? JSONEncoder().encode(configuration) { defaults.set(data, forKey: "serverConfig") }
        client.configuration = configuration
    }

    func loadMarket() async {
        do {
            let snapshot: QuoteSnapshot = try await client.get("/api/quotes")
            quotes = snapshot.quotes
            if selectedQuote == nil { selectedQuote = quotes.first }
        } catch { connection = .failed(error.localizedDescription) }
    }

    func selectQuote(_ quote: Quote) async {
        selectedQuote = quote
        do { bars = try await client.get("/api/quotes/\(quote.code)/bars", query: [.init(name: "limit", value: "60")]) }
        catch { toast = error.localizedDescription }
    }

    func loadPortfolio() async {
        do { portfolio = try await client.get("/api/portfolio") }
        catch { connection = .failed(error.localizedDescription) }
    }

    func loadBaskets() async {
        do { baskets = try await client.get("/api/baskets") }
        catch { connection = .failed(error.localizedDescription) }
    }

    func basketDetail(_ basket: Basket) async throws -> BasketDetail {
        let encoded = basket.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? basket.id
        return try await client.get("/api/baskets/\(encoded)")
    }

    func loadPredictions() async {
        do { let result: PredictionEnvelope = try await client.get("/api/agent/predictions", query: [.init(name: "limit", value: "20")]); predictions = result.predictions }
        catch { predictions = [] }
    }

    func createConversation() {
        guard !isResponding else { return }
        let conversation = Conversation()
        conversations.insert(conversation, at: 0); activeConversationID = conversation.id; messages = []
        persistConversations()
    }

    func deleteConversations(at offsets: IndexSet) {
        guard !isResponding else { return }
        let removingActive = offsets.contains { conversations[$0].id == activeConversationID }
        conversations.remove(atOffsets: offsets)
        if conversations.isEmpty { conversations = [Conversation()] }
        if removingActive { activeConversationID = conversations[0].id; Task { await loadConversation(activeConversationID) } }
        persistConversations()
    }

    func loadConversation(_ id: String) async {
        guard !isResponding else { return }
        activeConversationID = id; messages = []
        do {
            let history: HistoryEnvelope = try await client.get("/api/agent/history", query: [.init(name: "session_id", value: id), .init(name: "limit", value: "100")])
            messages = history.messages.compactMap { row in
                guard let role = ChatMessage.Role(rawValue: row.role) else { return nil }
                return ChatMessage(role: role, content: row.content)
            }
        } catch { toast = error.localizedDescription }
    }

    func send(_ raw: String) async {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isResponding else { return }
        messages.append(ChatMessage(role: .user, content: text))
        messages.append(ChatMessage(role: .assistant, content: ""))
        let conversationID = activeConversationID
        let responseID = messages[messages.count - 1].id
        isResponding = true; activeTools = []
        updateConversation(conversationID, with: text)
        do {
            try await client.streamAgent(message: text, sessionID: conversationID) { event in
                guard self.activeConversationID == conversationID,
                      let responseIndex = self.messages.firstIndex(where: { $0.id == responseID }) else { return }
                switch event["type"] as? String {
                case "chunk": self.messages[responseIndex].content += event["text"] as? String ?? ""
                case "tool_call_started": if let tool = event["tool"] as? String { self.activeTools.append(tool) }
                case "tool_call_finished": if let tool = event["tool"] as? String { self.activeTools.removeAll { $0 == tool }; self.messages[responseIndex].tools.append(tool) }
                case "error": self.messages[responseIndex].content = event["message"] as? String ?? "AI 暂时不可用"
                default: break
                }
            }
        } catch {
            updateResponse(responseID, in: conversationID) { $0.content = error.localizedDescription }
        }
        isResponding = false; activeTools = []
        updateResponse(responseID, in: conversationID) { message in
            if message.content.isEmpty { message.content = "这次没有收到回复，请稍后再试。" }
        }
        if activeConversationID == conversationID,
           let response = messages.first(where: { $0.id == responseID }) {
            updateConversation(conversationID, with: response.content)
        }
    }

    private func updateResponse(_ responseID: UUID, in conversationID: String, mutation: (inout ChatMessage) -> Void) {
        guard activeConversationID == conversationID,
              let index = messages.firstIndex(where: { $0.id == responseID }) else { return }
        mutation(&messages[index])
    }

    private func updateConversation(_ conversationID: String, with text: String) {
        guard let index = conversations.firstIndex(where: { $0.id == conversationID }) else { return }
        if conversations[index].title == "新对话" || conversations[index].title == "开盘聊聊" {
            conversations[index].title = String(text.prefix(18))
        }
        conversations[index].preview = String(text.prefix(48)); conversations[index].updatedAt = .now
        let item = conversations.remove(at: index); conversations.insert(item, at: 0)
        persistConversations()
    }

    private func persistConversations() {
        if let data = try? JSONEncoder().encode(conversations) { defaults.set(data, forKey: "conversations") }
    }
}
