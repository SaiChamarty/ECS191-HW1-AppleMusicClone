import Foundation

/// Abstraction over the song source so a real search API (e.g. the iTunes
/// Search API) can replace the hard-coded catalog without touching the UI.
protocol SongSearching {
    /// Songs shown under "Popular searches".
    func popularSongs() async throws -> [Song]
    /// Songs whose title or artist matches `query`.
    func search(_ query: String) async throws -> [Song]
}

/// Searches the bundled `Catalog`.
struct LocalCatalog: SongSearching {
    var songs: [Song] = Catalog.songs

    func popularSongs() async throws -> [Song] {
        Array(songs.prefix(12))
    }

    func search(_ query: String) async throws -> [Song] {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }
        return songs.filter { "\($0.title) \($0.artist)".localizedCaseInsensitiveContains(query) }
    }
}

/// Searches the whole iTunes catalog (no key needed) in the user's storefront.
/// Popular songs are that storefront's live top-songs chart. Both fall back
/// to the bundled list when the network is unavailable.
struct ITunesCatalog: SongSearching {
    var country: String = ITunesCatalog.storefront
    var limit = 25
    var popularCount = 12
    var fallback = LocalCatalog()
    var session: URLSession = .shared

    /// Two-letter App Store country for the current region, e.g. "us", "in", "jp".
    static var storefront: String {
        Locale.current.region?.identifier.lowercased() ?? "us"
    }

    func popularSongs() async throws -> [Song] {
        // Some storefronts have no music chart (e.g. Korea); use the US chart there.
        var storefronts = [country]
        if country != "us" { storefronts.append("us") }
        for storefront in storefronts {
            try Task.checkCancellation()
            if let songs = try? await topSongs(in: storefront), !songs.isEmpty {
                return songs
            }
        }
        return try await fallback.popularSongs()
    }

    /// Chart track IDs (one request), then one batch lookup for artwork and previews.
    private func topSongs(in storefront: String) async throws -> [Song] {
        // Fetch extra, since some chart entries have no preview.
        guard let chartURL = URL(string: "https://itunes.apple.com/\(storefront)/rss/topsongs/limit=\(popularCount * 2)/json")
        else { throw URLError(.badURL) }
        let chart = try JSONDecoder().decode(ChartFeed.self, from: try await fetch(chartURL))
        let ids = chart.feed.entry?.compactMap { Int($0.id.attributes.imID) } ?? []
        guard !ids.isEmpty else { return [] }

        var components = URLComponents(string: "https://itunes.apple.com/lookup")
        components?.queryItems = [
            URLQueryItem(name: "id", value: ids.map(String.init).joined(separator: ",")),
            URLQueryItem(name: "country", value: storefront),
        ]
        guard let lookupURL = components?.url else { throw URLError(.badURL) }
        let results = try JSONDecoder().decode(SearchResponse.self, from: try await fetch(lookupURL)).results
        // Lookup doesn't promise order; keep chart order.
        let byID = Dictionary(results.compactMap { result in result.song.map { ($0.trackID ?? 0, $0) } },
                              uniquingKeysWith: { first, _ in first })
        // Charts often list several versions of one hit ("… (Piano Version)"); keep the first.
        var seen = Set<String>()
        let unique = ids.compactMap { byID[$0] }.filter { seen.insert(Self.versionKey($0)).inserted }
        return Array(unique.prefix(popularCount))
    }

    /// Title without bracketed version notes, plus artist: "patient zero|taylor swift".
    static func versionKey(_ song: Song) -> String {
        let base = song.title.split(whereSeparator: { "([".contains($0) }).first.map(String.init) ?? song.title
        return "\(base.trimmingCharacters(in: .whitespaces).lowercased())|\(song.artist.lowercased())"
    }

    private func fetch(_ url: URL) async throws -> Data {
        let (data, response) = try await session.data(from: url)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private struct ChartFeed: Decodable {
        struct Feed: Decodable {
            let entry: [Entry]?
        }

        struct Entry: Decodable {
            struct ID: Decodable {
                struct Attributes: Decodable {
                    let imID: String

                    enum CodingKeys: String, CodingKey {
                        case imID = "im:id"
                    }
                }

                let attributes: Attributes
            }

            let id: ID
        }

        let feed: Feed
    }

    func search(_ query: String) async throws -> [Song] {
        let query = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }
        do {
            return try await searchITunes(query)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            return try await fallback.search(query)
        }
    }

    private func searchITunes(_ query: String) async throws -> [Song] {
        var components = URLComponents(string: "https://itunes.apple.com/search")
        components?.queryItems = [
            URLQueryItem(name: "term", value: query),
            URLQueryItem(name: "media", value: "music"),
            URLQueryItem(name: "entity", value: "song"),
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "country", value: country),
        ]
        guard let url = components?.url else { throw URLError(.badURL) }
        let results = try JSONDecoder().decode(SearchResponse.self, from: try await fetch(url)).results
        // Only songs with a preview can be analyzed; keep the first of each title+artist.
        var seen = Set<Song.ID>()
        return results.compactMap(\.song).filter { seen.insert($0.id).inserted }
    }

    private struct SearchResponse: Decodable {
        let results: [Result]
    }

    private struct Result: Decodable {
        let kind: String?
        let trackId: Int?
        let trackName: String?
        let artistName: String?
        let collectionName: String?
        let primaryGenreName: String?
        let releaseDate: String?
        let previewUrl: String?
        let artworkUrl100: String?

        var song: Song? {
            guard kind == "song", let trackId, let trackName, let artistName,
                  let preview = previewUrl.flatMap(URL.init(string:))
            else { return nil }
            return Song(
                title: trackName,
                artist: artistName,
                year: releaseDate.flatMap { Int($0.prefix(4)) } ?? 0,
                trackID: trackId,
                album: collectionName,
                genre: primaryGenreName,
                previewURL: preview,
                // 100px thumbnails can be requested at a larger size by URL.
                artworkURL: artworkUrl100.flatMap { URL(string: $0.replacingOccurrences(of: "100x100bb", with: "300x300bb")) }
            )
        }
    }
}

enum Catalog {
    static let songs: [Song] = [
        Song(title: "Midnight City", artist: "M83", year: 2011, tags: ["synth", "dream", "electronic"]),
        Song(title: "Let It Happen", artist: "Tame Impala", year: 2015, tags: ["psych", "synth", "dream"]),
        Song(title: "Dreams", artist: "Fleetwood Mac", year: 1977, tags: ["soft rock", "70s", "mellow"]),
        Song(title: "Electric Feel", artist: "MGMT", year: 2007, tags: ["psych", "synth", "indie"]),
        Song(title: "Motion Sickness", artist: "Phoebe Bridgers", year: 2017, tags: ["indie", "sad", "folk"]),
        Song(title: "Redbone", artist: "Childish Gambino", year: 2016, tags: ["funk", "soul", "rnb"]),
        Song(title: "Nights", artist: "Frank Ocean", year: 2016, tags: ["rnb", "soul", "dream"]),
        Song(title: "Teardrop", artist: "Massive Attack", year: 1998, tags: ["trip hop", "electronic", "mellow"]),
        Song(title: "Heroes", artist: "David Bowie", year: 1977, tags: ["70s", "rock", "synth"]),
        Song(title: "Pink + White", artist: "Frank Ocean", year: 2016, tags: ["rnb", "soul", "mellow"]),
        Song(title: "Myth", artist: "Beach House", year: 2012, tags: ["dream", "indie", "mellow"]),
        Song(title: "Reptilia", artist: "The Strokes", year: 2003, tags: ["rock", "indie", "garage"]),
        Song(title: "Superstition", artist: "Stevie Wonder", year: 1972, tags: ["funk", "soul", "70s"]),
        Song(title: "Holocene", artist: "Bon Iver", year: 2011, tags: ["folk", "indie", "mellow"]),
        Song(title: "Get Lucky", artist: "Daft Punk", year: 2013, tags: ["funk", "electronic", "disco"]),
        Song(title: "Running Up That Hill", artist: "Kate Bush", year: 1985, tags: ["synth", "80s", "art pop"]),
        Song(title: "Do I Wanna Know?", artist: "Arctic Monkeys", year: 2013, tags: ["rock", "indie", "garage"]),
        Song(title: "Retrograde", artist: "James Blake", year: 2013, tags: ["electronic", "soul", "sad"]),
        Song(title: "Golden Hour", artist: "Kacey Musgraves", year: 2018, tags: ["folk", "mellow", "country"]),
        Song(title: "Everything In Its Right Place", artist: "Radiohead", year: 2000, tags: ["electronic", "art pop", "sad"]),
        Song(title: "Kyoto", artist: "Phoebe Bridgers", year: 2020, tags: ["indie", "folk", "rock"]),
        Song(title: "Ivy", artist: "Frank Ocean", year: 2016, tags: ["rnb", "indie", "sad"]),
        Song(title: "Blue Monday", artist: "New Order", year: 1983, tags: ["synth", "80s", "electronic"]),
        Song(title: "Space Song", artist: "Beach House", year: 2015, tags: ["dream", "indie", "sad"]),
        Song(title: "September", artist: "Earth, Wind & Fire", year: 1978, tags: ["funk", "disco", "70s"]),
        Song(title: "Lost in Yesterday", artist: "Tame Impala", year: 2020, tags: ["psych", "synth", "indie"]),
    ]

    /// Returns the catalog entry for `song` (with tags) if it exists.
    static func entry(for song: Song) -> Song? {
        songs.first { $0.id == song.id }
    }
}
