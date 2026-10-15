import Foundation

protocol SimilarSongsProviding {
    func similar(to song: Song) async throws -> [Song]

    /// First results, then improved results as the provider learns more
    /// (the similarity service analyzes more candidate songs after a query).
    func similarUpdates(to song: Song) -> AsyncThrowingStream<[Song], Error>
}

extension SimilarSongsProviding {
    /// Default: a single answer.
    func similarUpdates(to song: Song) -> AsyncThrowingStream<[Song], Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    continuation.yield(try await similar(to: song))
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

/// Tries each provider in order and uses the first one that returns songs.
struct FirstAvailableSimilarSongs: SimilarSongsProviding {
    let providers: [SimilarSongsProviding]

    func similar(to song: Song) async throws -> [Song] {
        for try await songs in similarUpdates(to: song) {
            return songs
        }
        return []
    }

    func similarUpdates(to song: Song) -> AsyncThrowingStream<[Song], Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                var lastError: Error = CancellationError()
                for provider in providers {
                    if Task.isCancelled { break }
                    var answered = false
                    do {
                        for try await songs in provider.similarUpdates(to: song) where !songs.isEmpty {
                            answered = true
                            continuation.yield(songs)
                        }
                    } catch {
                        lastError = error
                    }
                    // Once a provider has answered, stay with it.
                    if answered {
                        continuation.finish()
                        return
                    }
                }
                continuation.finish(throwing: lastError)
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}

// MARK: - Similarity service

/// Calls the SoundAlike similarity service (`similarity-service/` in this repo),
/// which ranks indexed songs by audio features, tags, metadata and tempo.
///
/// The base URL comes from the `SimilarityServiceURL` Info.plist entry
/// (the hosted service, https://soundalike.junebase.com).
/// See README.md for the API contract.
///
/// After answering, the service keeps analyzing candidate songs around the
/// query (same artist, genre charts in the user's storefront). While it reports
/// `expanding`, `similarUpdates` re-asks every few seconds and yields the
/// improved list.
struct SimilarityServiceClient: SimilarSongsProviding {
    enum ServiceError: Error {
        case notConfigured
        case badStatus(Int)
    }

    let baseURL: URL?
    var explain = false
    var country = ITunesCatalog.storefront
    var session: URLSession = .shared
    /// How often and how many times to re-ask while the service is expanding.
    var refreshInterval: Duration = .seconds(4)
    var maxRefreshes = 8

    init(baseURL: URL? = SimilarityServiceClient.configuredURL, explain: Bool = false) {
        self.baseURL = baseURL
        self.explain = explain
    }

    func similarUpdates(to song: Song) -> AsyncThrowingStream<[Song], Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var response = try await fetch(song)
                    continuation.yield(response.songs)
                    var refreshes = 0
                    while response.isExpanding, refreshes < maxRefreshes {
                        try await Task.sleep(for: refreshInterval)
                        refreshes += 1
                        let previous = response.songs.map(\.id)
                        // Ask by trackId now that the service has resolved the song.
                        response = try await fetch(song, trackID: response.queryTrackID)
                        if response.songs.map(\.id) != previous {
                            continuation.yield(response.songs)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// The hosted service from Info.plist, unless the `SIMILARITY_SERVICE_URL`
    /// environment variable (set in the Xcode scheme) points at a local server.
    static var configuredURL: URL? {
        let override = ProcessInfo.processInfo.environment["SIMILARITY_SERVICE_URL"]
        let plist = Bundle.main.object(forInfoDictionaryKey: "SimilarityServiceURL") as? String
        guard let value = [override, plist].compactMap({ $0 }).first(where: { !$0.isEmpty && !$0.hasPrefix("$(") })
        else { return nil }
        return URL(string: value)
    }

    func similar(to song: Song) async throws -> [Song] {
        try await fetch(song).songs
    }

    private func fetch(_ song: Song, trackID: Int? = nil) async throws -> SimilarResponse {
        guard let baseURL else { throw ServiceError.notConfigured }
        // Indexed songs return in well under a second; unindexed ones are
        // analyzed on demand (preview download + feature extraction).
        var request = URLRequest(url: baseURL.appending(path: "v1/similar"), timeoutInterval: 30)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "content-type")

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(
            SimilarRequest(
                trackId: trackID ?? song.trackID, title: song.title, artist: song.artist,
                country: country, limit: 10, explain: explain
            )
        )

        let (data, response) = try await session.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw ServiceError.badStatus(http.statusCode)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(SimilarResponse.self, from: data)
    }

    // MARK: Wire types

    private struct SimilarRequest: Encodable {
        let trackId: Int?
        let title: String
        let artist: String
        let country: String
        let limit: Int
        let explain: Bool
    }

    private struct SimilarResponse: Decodable {
        struct Query: Decodable {
            let trackId: Int
        }

        let query: Query
        let results: [Result]
        /// True while the service is still analyzing candidates for this query.
        let expanding: Bool?

        var songs: [Song] { results.map(\.song) }
        var queryTrackID: Int { query.trackId }
        var isExpanding: Bool { expanding ?? false }
    }

    private struct Result: Decodable {
        struct Breakdown: Decodable {
            let audio: Double
            let tags: Double
            let metadata: Double
            let tempo: Double
        }

        let track: Track
        let score: Double
        let breakdown: Breakdown
        let reason: String?

        var song: Song {
            Song(
                title: track.title,
                artist: track.artist,
                year: track.year,
                why: reason ?? whyLine,
                trackID: track.trackId,
                album: track.album,
                genre: track.genre,
                previewURL: URL(string: track.previewUrl),
                artworkURL: URL(string: track.artworkUrl)
            )
        }

        /// e.g. "52% match · sound 55% · 118 BPM · chill" when there's no Claude reason.
        /// Leads with the overall score, which is what the list is ranked by.
        private var whyLine: String {
            var parts = [
                "\(Int((score * 100).rounded()))% match",
                "sound \(Int((breakdown.audio * 100).rounded()))%",
            ]
            if track.bpm > 0 { parts.append("\(Int(track.bpm.rounded())) BPM") }
            if track.context != "unknown" { parts.append(track.context.replacingOccurrences(of: "_", with: " ")) }
            return parts.joined(separator: " · ")
        }
    }

    private struct Track: Decodable {
        let trackId: Int
        let title: String
        let artist: String
        let album: String
        let genre: String
        let year: Int
        let previewUrl: String
        let artworkUrl: String
        let bpm: Double
        let context: String
    }
}

// MARK: - Anthropic

/// Asks Claude for 10 songs that sound like `song`.
///
/// The API key is read from the `AnthropicAPIKey` Info.plist entry, which is
/// filled from `ANTHROPIC_API_KEY` in the gitignored `Secrets.xcconfig`.
///
/// IMPORTANT: Any key shipped inside an app binary can be extracted. This is
/// fine for local development only — production builds should call a backend
/// proxy that holds the key and forwards requests to the Anthropic API.
struct AnthropicSimilarSongs: SimilarSongsProviding {
    enum ServiceError: Error {
        case missingAPIKey
        case invalidURL
        case badStatus(Int)
        case refusal
        case noJSONArray
        case emptyResult
    }

    let apiKey: String?
    var model = "claude-opus-5"

    init(apiKey: String? = Bundle.main.object(forInfoDictionaryKey: "AnthropicAPIKey") as? String) {
        self.apiKey = apiKey
    }

    func similar(to song: Song) async throws -> [Song] {
        let key = (apiKey ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        // An unexpanded "$(ANTHROPIC_API_KEY)" means Secrets.xcconfig isn't wired up.
        guard !key.isEmpty, !key.hasPrefix("$(") else { throw ServiceError.missingAPIKey }
        guard let url = URL(string: "https://api.anthropic.com/v1/messages") else { throw ServiceError.invalidURL }

        let yearText = song.year > 0 ? " (\(song.year))" : ""
        let prompt = """
        List exactly 10 real songs that sound similar to "\(song.title)" by \(song.artist)\(yearText). \
        Exclude that song. Reply with ONLY a JSON array of objects: {"title","artist","year","why"} \
        where "why" is under 9 words describing the sonic similarity.
        """

        let body = MessagesRequest(
            model: model,
            maxTokens: 16000,
            // Re-runs the request on Anthropic's recommended fallback model if
            // a safety classifier declines it.
            fallbacks: "default",
            // A short list doesn't need deep reasoning; keeps latency low.
            outputConfig: .init(effort: "low"),
            messages: [.init(role: "user", content: prompt)]
        )

        var request = URLRequest(url: url, timeoutInterval: 45)
        request.httpMethod = "POST"
        request.setValue(key, forHTTPHeaderField: "x-api-key")
        request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        request.setValue("server-side-fallback-2026-07-01", forHTTPHeaderField: "anthropic-beta")
        request.setValue("application/json", forHTTPHeaderField: "content-type")

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw ServiceError.badStatus(http.statusCode)
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let message = try decoder.decode(MessagesResponse.self, from: data)
        guard message.stopReason != "refusal" else { throw ServiceError.refusal }

        let text = message.content.compactMap { $0.type == "text" ? $0.text : nil }.joined()
        guard let json = Self.firstJSONArray(in: text) else { throw ServiceError.noJSONArray }

        let items = try JSONDecoder().decode([SimilarItem].self, from: Data(json.utf8))
        let songs = items
            .map { Song(title: $0.title, artist: $0.artist, year: $0.year ?? 0, why: $0.why) }
            .filter { $0.id != song.id }
        guard !songs.isEmpty else { throw ServiceError.emptyResult }
        return Array(songs.prefix(10))
    }

    /// Returns the first balanced `[...]` in `text`, ignoring brackets inside JSON strings.
    static func firstJSONArray(in text: String) -> String? {
        guard let start = text.firstIndex(of: "[") else { return nil }
        var depth = 0
        var inString = false
        var isEscaped = false
        var index = start
        while index < text.endIndex {
            let character = text[index]
            if inString {
                if isEscaped {
                    isEscaped = false
                } else if character == "\\" {
                    isEscaped = true
                } else if character == "\"" {
                    inString = false
                }
            } else if character == "\"" {
                inString = true
            } else if character == "[" {
                depth += 1
            } else if character == "]" {
                depth -= 1
                if depth == 0 {
                    return String(text[start...index])
                }
            }
            index = text.index(after: index)
        }
        return nil
    }

    // MARK: Wire types

    private struct MessagesRequest: Encodable {
        struct OutputConfig: Encodable {
            let effort: String
        }

        struct Message: Encodable {
            let role: String
            let content: String
        }

        let model: String
        let maxTokens: Int
        let fallbacks: String
        let outputConfig: OutputConfig
        let messages: [Message]
    }

    private struct MessagesResponse: Decodable {
        struct Block: Decodable {
            let type: String
            let text: String?
        }

        let content: [Block]
        let stopReason: String?
    }

    private struct SimilarItem: Decodable {
        let title: String
        let artist: String
        let year: Int?
        let why: String?

        enum CodingKeys: String, CodingKey {
            case title, artist, year, why
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.container(keyedBy: CodingKeys.self)
            title = try container.decode(String.self, forKey: .title)
            artist = try container.decode(String.self, forKey: .artist)
            why = try container.decodeIfPresent(String.self, forKey: .why)
            // The model occasionally returns the year as a string.
            if let number = try? container.decodeIfPresent(Int.self, forKey: .year) {
                year = number
            } else if let string = try? container.decodeIfPresent(String.self, forKey: .year) {
                year = Int(string.prefix(4))
            } else {
                year = nil
            }
        }
    }
}

// MARK: - Local fallback

/// Offline ranking over the bundled catalog by shared tags and era.
struct LocalSimilarSongs: SimilarSongsProviding {
    var catalog: [Song] = Catalog.songs
    /// Artificial delay so the loading state is visible.
    var delay: Duration = .milliseconds(1100)

    func similar(to song: Song) async throws -> [Song] {
        try await Task.sleep(for: delay)
        return ranked(for: song)
    }

    /// Scores each other song as (shared tags × 10) − |year difference| / 10
    /// and returns the top 10.
    func ranked(for song: Song) -> [Song] {
        struct Candidate {
            let offset: Int
            let song: Song
            let shared: [String]
            let score: Double
        }

        let sourceTags = Set(song.tags)
        var candidates: [Candidate] = []
        for (offset, candidate) in catalog.enumerated() where candidate.id != song.id {
            let shared = candidate.tags.filter { sourceTags.contains($0) }
            let yearPenalty = Double(abs(candidate.year - song.year)) / 10
            let score = Double(shared.count * 10) - yearPenalty
            candidates.append(Candidate(offset: offset, song: candidate, shared: shared, score: score))
        }
        // Ties keep catalog order so results are deterministic.
        let scored = candidates.sorted { lhs, rhs in
            lhs.score != rhs.score ? lhs.score > rhs.score : lhs.offset < rhs.offset
        }

        return scored.prefix(10).map { entry in
            var result = entry.song
            let tags = entry.shared.joined(separator: ", ")
            let lead: String = tags.isEmpty ? "Similar era" : tags.prefix(1).uppercased() + String(tags.dropFirst())
            result.why = lead + " — shared feel"
            return result
        }
    }
}
