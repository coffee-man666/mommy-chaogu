import Foundation

struct ServerConfiguration: Codable, Equatable {
    var baseURL = "http://127.0.0.1:8000"
    var accessToken = ""
    var voiceGatewayURL = ""
}
enum APIError: LocalizedError {
    case invalidURL, badResponse(Int, String), decoding(String), transport(String)
    var errorDescription: String? {
        switch self {
        case .invalidURL: "服务地址不正确"
        case let .badResponse(code, detail): "服务返回错误（\(code)）：\(detail)"
        case let .decoding(message): "服务数据格式不兼容：\(message)"
        case let .transport(message): "连接失败：\(message)"
        }
    }
}

final class APIClient {
    private let session: URLSession
    var configuration: ServerConfiguration

    init(configuration: ServerConfiguration, sessionConfiguration: URLSessionConfiguration = .default) {
        self.configuration = configuration
        let config = sessionConfiguration
        config.timeoutIntervalForRequest = 20
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config)
    }

    func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        try await request(path, method: "GET", query: query, body: Optional<String>.none)
    }

    func post<T: Decodable, Body: Encodable>(_ path: String, body: Body?) async throws -> T {
        try await request(path, method: "POST", query: [], body: body)
    }

    private func request<T: Decodable, Body: Encodable>(_ path: String, method: String, query: [URLQueryItem], body: Body?) async throws -> T {
        guard var components = URLComponents(string: configuration.baseURL + path) else { throw APIError.invalidURL }
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw APIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if !configuration.accessToken.isEmpty { request.setValue("Bearer \(configuration.accessToken)", forHTTPHeaderField: "Authorization") }
        if let body { request.httpBody = try JSONEncoder().encode(body); request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIError.transport("无效响应") }
            guard 200..<300 ~= http.statusCode else {
                let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String ?? String(data: data, encoding: .utf8) ?? "未知错误"
                throw APIError.badResponse(http.statusCode, detail)
            }
            return try JSONDecoder().decode(T.self, from: data)
        } catch let error as APIError { throw error }
        catch let error as DecodingError { throw APIError.decoding(Self.describe(error)) }
        catch { throw APIError.transport(error.localizedDescription) }
    }

    private static func describe(_ error: DecodingError) -> String {
        switch error {
        case let .keyNotFound(key, context): "缺少字段 \(key.stringValue)（\(context.codingPath.map(\.stringValue).joined(separator: "."))）"
        case let .typeMismatch(_, context): "字段类型错误（\(context.codingPath.map(\.stringValue).joined(separator: "."))）"
        case let .valueNotFound(_, context): "字段值为空（\(context.codingPath.map(\.stringValue).joined(separator: "."))）"
        case let .dataCorrupted(context): "JSON 数据损坏（\(context.codingPath.map(\.stringValue).joined(separator: "."))）"
        @unknown default: error.localizedDescription
        }
    }

    func streamAgent(message: String, sessionID: String, onEvent: @escaping @MainActor ([String: Any]) -> Void) async throws {
        let ticket: WSTicket = try await post("/api/auth/ws-ticket", body: Optional<String>.none)
        guard var components = URLComponents(string: configuration.baseURL) else { throw APIError.invalidURL }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/ws/agent"
        components.queryItems = [URLQueryItem(name: "ticket", value: ticket.ticket)]
        guard let url = components.url else { throw APIError.invalidURL }
        let socket = session.webSocketTask(with: url)
        socket.resume()
        let payload: [String: Any] = ["message": message, "session_id": sessionID]
        let data = try JSONSerialization.data(withJSONObject: payload)
        try await socket.send(.data(data))
        defer { socket.cancel(with: .normalClosure, reason: nil) }
        while true {
            let frame = try await socket.receive()
            let data: Data
            switch frame { case let .data(value): data = value; case let .string(value): data = Data(value.utf8); @unknown default: continue }
            guard let event = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            await onEvent(event)
            if event["type"] as? String == "done" || event["type"] as? String == "error" { return }
        }
    }
}
