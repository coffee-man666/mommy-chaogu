import AVFoundation
import Speech

@MainActor
final class VoiceCommandController: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    @Published var isListening = false
    @Published var transcript = ""
    @Published var authorizationDenied = false
    @Published var isSpeaking = false

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let engine = AVAudioEngine()
    private let synthesizer = AVSpeechSynthesizer()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func toggleListening() async {
        if isListening { stopListening(); return }
        let speech = await requestSpeechAuthorization()
        let mic = await AVAudioApplication.requestRecordPermission()
        guard speech == .authorized, mic else { authorizationDenied = true; return }
        do { try startListening() } catch { authorizationDenied = true }
    }

    private func requestSpeechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func startListening() throws {
        task?.cancel(); task = nil
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers, .allowBluetoothHFP])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        self.request = request
        let node = engine.inputNode
        let format = node.outputFormat(forBus: 0)
        node.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in request.append(buffer) }
        engine.prepare(); try engine.start(); isListening = true; transcript = ""
        task = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                if let result { self?.transcript = result.bestTranscription.formattedString }
                if error != nil || result?.isFinal == true { self?.stopListening() }
            }
        }
    }

    func stopListening() {
        guard isListening else { return }
        engine.stop(); engine.inputNode.removeTap(onBus: 0); request?.endAudio(); task?.cancel()
        request = nil; task = nil; isListening = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func speak(_ text: String) {
        if isListening { stopListening() }
        synthesizer.stopSpeaking(at: .immediate)
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
        } catch {
            isSpeaking = false
            return
        }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
        utterance.rate = 0.5
        synthesizer.speak(utterance)
    }

    func stopSpeaking() {
        synthesizer.stopSpeaking(at: .immediate); isSpeaking = false
        deactivateAudioSessionIfIdle()
    }

    private func deactivateAudioSessionIfIdle() {
        guard !synthesizer.isSpeaking, !isListening else { return }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) { Task { @MainActor in self.isSpeaking = true } }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) { Task { @MainActor in self.isSpeaking = false; self.deactivateAudioSessionIfIdle() } }
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) { Task { @MainActor in self.isSpeaking = false; self.deactivateAudioSessionIfIdle() } }
}
