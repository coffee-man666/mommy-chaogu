import SwiftUI

struct ConversationsView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    @StateObject private var voice = VoiceCommandController()
    @State private var draft = ""
    @State private var showSessions = false
    @State private var voiceMode = false

    var body: some View {
        VStack(spacing: 0) {
            if store.messages.isEmpty { welcome }
            else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 14) {
                            ForEach(store.messages) { message in ChatBubble(message: message).id(message.id) }
                            if store.isResponding { WorkingRow(tools: store.activeTools) }
                        }.padding(16)
                    }.onChange(of: store.messages) { _, messages in if let id = messages.last?.id { withAnimation { proxy.scrollTo(id, anchor: .bottom) } } }
                }
            }
            composer
        }
        .background(palette.background)
        .navigationTitle(store.conversations.first(where: { $0.id == store.activeConversationID })?.title ?? "AI")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) { Button { showSessions = true } label: { Image(systemName: "sidebar.left") }.disabled(store.isResponding) }
            ToolbarItem(placement: .topBarTrailing) { Button { store.createConversation() } label: { Image(systemName: "square.and.pencil") }.disabled(store.isResponding) }
        }
        .sheet(isPresented: $showSessions) { ConversationLibraryView(isPresented: $showSessions) }
        .onChange(of: voice.transcript) { _, value in draft = value }
        .onChange(of: store.isResponding) { old, new in
            if old, !new, voiceMode, let answer = store.messages.last(where: { $0.role == .assistant })?.content { voice.speak(answer) }
        }
        .alert("无法使用语音", isPresented: $voice.authorizationDenied) { Button("知道了", role: .cancel) {} } message: { Text("请在系统设置中允许麦克风和语音识别权限。") }
    }

    private var welcome: some View {
        ScrollView {
            VStack(spacing: 22) {
                Spacer(minLength: 54)
                ZStack { Circle().fill(palette.accent.opacity(0.14)).frame(width: 88, height: 88); Image(systemName: "waveform").font(.system(size: 36)).foregroundStyle(palette.accent) }
                VStack(spacing: 7) { Text("今天想研究什么？").font(.title.bold()); Text("我能看行情、查持仓、分析篮子，\n也会记住你的判断和偏好。").foregroundStyle(palette.secondary).multilineTextAlignment(.center) }
                LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 10) {
                    suggestion("复盘全部持仓", "briefcase")
                    suggestion("今天市场怎么样", "chart.line.uptrend.xyaxis")
                    suggestion("找最强股票篮子", "square.grid.2x2")
                    suggestion("回顾我的判断", "brain.head.profile")
                }
            }.padding(20)
        }
    }

    private func suggestion(_ text: String, _ icon: String) -> some View {
        Button { draft = text; submit() } label: { VStack(alignment: .leading, spacing: 12) { Image(systemName: icon).foregroundStyle(palette.accent); Text(text).font(.subheadline.weight(.semibold)).foregroundStyle(palette.text).frame(maxWidth: .infinity, alignment: .leading) }.padding(14).background(palette.surface, in: RoundedRectangle(cornerRadius: 17)) }.buttonStyle(.plain)
    }

    private var composer: some View {
        VStack(spacing: 8) {
            if voice.isListening { HStack { Image(systemName: "waveform"); Text(voice.transcript.isEmpty ? "正在听…" : voice.transcript).lineLimit(1); Spacer(); Text("点按结束").font(.caption) }.foregroundStyle(palette.accent).padding(.horizontal, 12) }
            HStack(alignment: .bottom, spacing: 9) {
                Button { voiceMode.toggle(); Task { await voice.toggleListening() } } label: { Image(systemName: voice.isListening ? "stop.fill" : "mic.fill").frame(width: 42, height: 42).background(voice.isListening ? palette.accent : palette.elevated, in: Circle()).foregroundStyle(voice.isListening ? palette.background : palette.text) }
                TextField("问行情、持仓或任何判断…", text: $draft, axis: .vertical).lineLimit(1...5).padding(.horizontal, 14).padding(.vertical, 11).background(palette.elevated, in: RoundedRectangle(cornerRadius: 20))
                Button(action: submit) { Image(systemName: "arrow.up").font(.headline).frame(width: 42, height: 42).background(draft.trimmingCharacters(in: .whitespaces).isEmpty ? palette.elevated : palette.accent, in: Circle()).foregroundStyle(draft.trimmingCharacters(in: .whitespaces).isEmpty ? palette.secondary : palette.background) }.disabled(store.isResponding || draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }.padding(.horizontal, 12).padding(.top, 10).padding(.bottom, 6).background(.ultraThinMaterial)
    }

    private func submit() {
        let text = draft; guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        voice.stopListening(); draft = ""; Task { await store.send(text) }
    }
}
struct ChatBubble: View {
    @Environment(\.appPalette) private var palette
    let message: ChatMessage
    var body: some View {
        HStack(alignment: .bottom) {
            if message.role == .user { Spacer(minLength: 52) }
            VStack(alignment: .leading, spacing: 8) {
                Text(message.content.isEmpty ? "…" : message.content).textSelection(.enabled)
                if !message.tools.isEmpty { Label("已调用 \(message.tools.count) 个数据工具", systemImage: "wrench.and.screwdriver").font(.caption2).foregroundStyle(palette.secondary) }
            }.padding(.horizontal, 14).padding(.vertical, 11).background(message.role == .user ? palette.accent : palette.surface, in: RoundedRectangle(cornerRadius: 18)).foregroundStyle(message.role == .user ? palette.background : palette.text)
            if message.role != .user { Spacer(minLength: 30) }
        }
    }
}

struct WorkingRow: View {
    @Environment(\.appPalette) private var palette
    let tools: [String]
    var body: some View { HStack { ProgressView(); Text(tools.last.map { "正在调用 \($0)…" } ?? "正在思考…").font(.caption).foregroundStyle(palette.secondary); Spacer() }.padding(.horizontal, 8) }
}

struct ConversationLibraryView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.appPalette) private var palette
    @Binding var isPresented: Bool
    var body: some View {
        NavigationStack {
            List {
                ForEach(store.conversations) { conversation in
                    Button { Task { await store.loadConversation(conversation.id); isPresented = false } } label: {
                        VStack(alignment: .leading, spacing: 5) { HStack { Text(conversation.title).font(.headline).foregroundStyle(palette.text); Spacer(); if conversation.id == store.activeConversationID { Image(systemName: "checkmark.circle.fill").foregroundStyle(palette.accent) } }; Text(conversation.preview.isEmpty ? "开始一段新的研究" : conversation.preview).font(.caption).foregroundStyle(palette.secondary).lineLimit(1) }
                    }.disabled(store.isResponding)
                }.onDelete(perform: store.deleteConversations)
            }.scrollContentBackground(.hidden).background(palette.background).navigationTitle("全部对话").toolbar { ToolbarItem(placement: .topBarTrailing) { Button { store.createConversation(); isPresented = false } label: { Image(systemName: "square.and.pencil") }.disabled(store.isResponding) } }
        }
    }
}
