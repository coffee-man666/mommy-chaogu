import XCTest
@testable import MommyChaogu

final class APIClientTests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testDecodingFailureIsNotReportedAsTransportFailure() async throws {
        StubURLProtocol.handler = { request in
            let response = HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(#"{"unexpected":true}"#.utf8))
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        let client = APIClient(
            configuration: ServerConfiguration(baseURL: "https://example.test"),
            sessionConfiguration: configuration
        )

        do {
            let _: WSTicket = try await client.get("/ticket")
            XCTFail("Expected decoding to fail")
        } catch APIError.decoding {
            // Expected: malformed service data has its own user-facing error.
        } catch {
            XCTFail("Expected APIError.decoding, got \(error)")
        }
    }

    func testVoiceProviderRoundTripsThroughItsPersistedValue() throws {
        for provider in VoiceProvider.allCases {
            XCTAssertEqual(VoiceProvider(rawValue: provider.rawValue), provider)
        }
    }
}

private final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            XCTFail("StubURLProtocol handler was not configured")
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
