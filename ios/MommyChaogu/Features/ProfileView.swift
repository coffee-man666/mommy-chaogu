import SwiftUI

struct ProfileView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        List {
            Section {
                NavigationLink { PortfolioView() } label: { Label("持仓分析", systemImage: "briefcase.fill") }
                NavigationLink { MemoryView() } label: { Label("记忆与预测", systemImage: "brain.head.profile") }
            }
            Section("个性") {
                NavigationLink { ThemeSettingsView() } label: { Label("颜色主题", systemImage: "paintpalette.fill") }
                NavigationLink { SettingsView() } label: { Label("模型与连接", systemImage: "network") }
            }
            Section("状态") {
                LabeledContent("数据服务", value: statusText)
                LabeledContent("对话", value: "\(store.conversations.count) 个")
                LabeledContent("版本", value: "MVP 0.1")
            }
        }.scrollContentBackground(.hidden).background(palette.background).navigationTitle("我的")
    }
    private var statusText: String { if case .online = store.connection { "在线" } else { "待连接" } }
}

struct MemoryView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        List {
            Section { Text("AI 会把对话中的事实、偏好和可验证判断分层保存；每个对话独立保留短期上下文，长期记忆可跨会话使用。").font(.subheadline).foregroundStyle(palette.secondary) }
            Section("预测追踪") {
                if store.predictions.isEmpty { EmptyState(icon: "brain", title: "还没有预测", detail: "和 AI 讨论明确的方向与时间范围后，会自动生成跟踪记录") }
                ForEach(store.predictions) { item in
                    VStack(alignment: .leading, spacing: 6) { HStack { Text(item.code).font(.headline); Spacer(); Text(item.status).font(.caption.bold()).foregroundStyle(palette.accent) }; if let direction = item.direction { Text(direction).font(.subheadline) }; if let reasoning = item.reasoning { Text(reasoning).font(.caption).foregroundStyle(palette.secondary).lineLimit(3) } }.padding(.vertical, 5)
                }
            }
        }.scrollContentBackground(.hidden).background(palette.background).navigationTitle("记忆系统").task { await store.loadPredictions() }
    }
}

struct ThemeSettingsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                ForEach(AppTheme.allCases) { theme in
                    Button { withAnimation { store.theme = theme; store.saveSettings() } } label: {
                        HStack(spacing: 14) {
                            HStack(spacing: -6) { Circle().fill(theme.palette.accent).frame(width: 30); Circle().fill(theme.palette.positive).frame(width: 30); Circle().fill(theme.palette.negative).frame(width: 30) }.frame(width: 72)
                            VStack(alignment: .leading, spacing: 3) { Text(theme.title).font(.headline).foregroundStyle(theme.palette.text); Text(theme.subtitle).font(.caption).foregroundStyle(theme.palette.secondary) }
                            Spacer(); if store.theme == theme { Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.palette.accent) }
                        }.padding(17).background(theme.palette.surface, in: RoundedRectangle(cornerRadius: 20)).overlay(RoundedRectangle(cornerRadius: 20).stroke(store.theme == theme ? theme.palette.accent : .clear, lineWidth: 2))
                    }.buttonStyle(.plain)
                }
            }.padding(16)
        }.background(palette.background).navigationTitle("颜色主题")
    }
}

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    @State private var config = ServerConfiguration()
    @State private var voiceProvider = "系统语音 + Agent"
    var body: some View {
        Form {
            Section("妈咪炒股服务") {
                TextField("https://your-server", text: $config.baseURL).textInputAutocapitalization(.never).keyboardType(.URL)
                SecureField("访问令牌（可选）", text: $config.accessToken)
                Text("大模型密钥保留在服务端；App 不直接保存 DeepSeek、OpenAI、Kimi、MiniMax 或 GLM 的密钥。").font(.caption).foregroundStyle(palette.secondary)
            }
            Section("语音指挥") {
                Picker("语音引擎", selection: $voiceProvider) { Text("系统语音 + Agent").tag("系统语音 + Agent"); Text("MiniMax 实时语音").tag("MiniMax 实时语音") }
                if voiceProvider == "MiniMax 实时语音" { TextField("后端语音网关 WebSocket", text: $config.voiceGatewayURL).textInputAutocapitalization(.never).keyboardType(.URL); Text("实时语音通过你的后端网关转发，支持打断、连续对话与服务端工具调用，避免把模型密钥放进手机。").font(.caption).foregroundStyle(palette.secondary) }
            }
            Section("模型") {
                LabeledContent("当前模型", value: "由服务端配置")
                Text("支持 DeepSeek、OpenAI 兼容模型、Kimi、智谱 GLM 与 MiniMax。切换模型后无需更新 App。").font(.caption).foregroundStyle(palette.secondary)
            }
            Button("保存并重新连接") { store.configuration = config; store.saveSettings(); Task { await store.bootstrap() } }.frame(maxWidth: .infinity)
        }.scrollContentBackground(.hidden).background(palette.background).navigationTitle("模型与连接").onAppear { config = store.configuration }
    }
}
