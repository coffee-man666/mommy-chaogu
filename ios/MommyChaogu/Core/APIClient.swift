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
        case let .badResponse(code, detail):
            switch code {
            case 401: "服务未授权，请检查访问令牌"
            case 404: "服务接口不存在，请确认后端版本"
            case 503: detail.isEmpty ? "服务暂时不可用" : "服务暂不可用：\(detail)"
            case 500...599: "服务暂时不可用，请稍后再试"
            default: "服务返回错误（\(code)）：\(detail)"
            }
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

    func userMessage(for error: Error) -> String {
        if let apiError = error as? APIError {
            if case let .badResponse(code, detail) = apiError, code == 503 {
                return detail.contains("快照")
                    ? "服务已连接，但还没有生成首份行情。可能是休市、没有自选股，或数据源正在启动。"
                    : (apiError.errorDescription ?? "服务暂时不可用")
            }
            return apiError.errorDescription ?? "服务暂时不可用"
        }

        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain {
            switch URLError.Code(rawValue: nsError.code) {
            case .notConnectedToInternet, .cannotConnectToHost, .cannotFindHost:
                return "无法连接妈咪炒股服务，请确认后端已启动，并检查服务地址。"
            case .networkConnectionLost:
                return "与妈咪炒股服务的连接中断，请稍后重试。"
            case .timedOut:
                return "连接妈咪炒股服务超时，请确认后端可访问。"
            default:
                break
            }
        }

        let detail = error.localizedDescription.lowercased()
        if detail.contains("socket") || detail.contains("not connected") {
            return "AI 实时通道未连接，请确认后端已启动并可访问。"
        }
        return "连接妈咪炒股服务失败，请检查服务地址或稍后重试。"
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
        guard let text = String(data: data, encoding: .utf8) else {
            throw APIError.transport("AI 请求格式无效")
        }
        try await sendWhenConnected(socket, text: text)
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

    private func sendWhenConnected(_ socket: URLSessionWebSocketTask, text: String) async throws {
        var lastError: Error?
        for attempt in 0..<30 {
            do {
                // The backend reads websocket.receive_text(), so this must be
                // a text frame rather than a binary JSON frame.
                try await socket.send(.string(text))
                return
            } catch {
                lastError = error
                if attempt < 29 {
                    try await Task.sleep(nanoseconds: 100_000_000)
                }
            }
        }
        if let lastError { throw lastError }
        throw APIError.transport("连接 AI 实时通道超时")
    }
}
