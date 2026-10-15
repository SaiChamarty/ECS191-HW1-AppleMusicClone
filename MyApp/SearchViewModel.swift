import Foundation
import Observation

@Observable
final class SearchViewModel {
    enum SheetMode {
        case confirm
        case results
    }

    var query = ""
    var isSearchFocused = false
    var selectedSong: Song?
    var isSheetPresented = false
    var sheetMode: SheetMode = .confirm
    var isLoading = false
    var results: [Song] = []
    /// True while results are shown but the service is still analyzing more candidates.
    private(set) var isRefining = false

    private(set) var popular: [Song] = []
    private(set) var matches: [Song] = []

    /// Incremented on row taps / when results arrive; drives haptic feedback.
    private(set) var selectionCount = 0
    private(set) var resultsCount = 0

    /// Plays result previews.
    let player = PreviewPlayer()

    private let catalog: SongSearching
    private let primaryProvider: SimilarSongsProviding
    private let fallbackProvider: SimilarSongsProviding
    private var similarTask: Task<Void, Never>?

    init(
        catalog: SongSearching = ITunesCatalog(),
        // The similarity service first; the in-app Claude call is a dev fallback.
        primaryProvider: SimilarSongsProviding = FirstAvailableSimilarSongs(
            providers: [SimilarityServiceClient(), AnthropicSimilarSongs()]
        ),
        fallbackProvider: SimilarSongsProviding = LocalSimilarSongs()
    ) {
        self.catalog = catalog
        self.primaryProvider = primaryProvider
        self.fallbackProvider = fallbackProvider
    }

    // MARK: Search

    var trimmedQuery: String {
        query.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var showsDropdown: Bool {
        !trimmedQuery.isEmpty
    }

    /// Up to 3 suggestions: the query itself, then lowercased matching titles,
    /// then lowercased "title artist" strings.
    var suggestions: [String] {
        let query = trimmedQuery
        guard !query.isEmpty else { return [] }
        let lowered = query.lowercased()
        var seen: Set<String> = [lowered]
        var output = [query]

        let titles = matches.map { $0.title.lowercased() }.filter { $0.contains(lowered) }
        let titleArtists = matches.map { "\($0.title) \($0.artist)".lowercased() }
        for candidate in titles + titleArtists where output.count < 3 {
            if seen.insert(candidate).inserted {
                output.append(candidate)
            }
        }
        return output
    }

    func loadPopular() async {
        popular = (try? await catalog.popularSongs()) ?? []
    }

    /// Refreshes `matches` for the current query. Called from `.task(id: query)`,
    /// so a newer keystroke cancels an in-flight search.
    func refreshMatches() async {
        let query = trimmedQuery
        guard !query.isEmpty else {
            matches = []
            return
        }
        // Debounce: catalog search is a network call, and iTunes rate-limits.
        do {
            try await Task.sleep(for: .milliseconds(300))
        } catch {
            return
        }
        let found = (try? await catalog.search(query)) ?? []
        guard !Task.isCancelled else { return }
        matches = found
    }

    func applySuggestion(_ suggestion: String) {
        query = suggestion
    }

    func clearQuery() {
        query = ""
    }

    // MARK: Sheet

    func select(_ song: Song) {
        cancelSimilarSearch()
        selectedSong = song
        sheetMode = .confirm
        results = []
        isSearchFocused = false
        isSheetPresented = true
        selectionCount += 1
    }

    /// Tapping a result makes it the selection and returns to confirm mode.
    func selectResult(_ song: Song) {
        cancelSimilarSearch()
        // Keep the service's track details, plus catalog tags for the local fallback.
        if let entry = Catalog.entry(for: song) {
            selectedSong = Song(
                title: song.title, artist: song.artist, year: song.year > 0 ? song.year : entry.year,
                tags: entry.tags, trackID: song.trackID, album: song.album, genre: song.genre,
                previewURL: song.previewURL, artworkURL: song.artworkURL
            )
        } else {
            selectedSong = song
        }
        results = []
        sheetMode = .confirm
        selectionCount += 1
    }

    func dismissSheet() {
        cancelSimilarSearch()
        isSheetPresented = false
    }

    /// "Find similar" action on any song row: opens the sheet and starts the search.
    func findSimilar(to song: Song) {
        select(song)
        findSimilar()
    }

    func findSimilar() {
        guard let song = selectedSong, !isLoading else { return }
        isLoading = true
        similarTask = Task { [primaryProvider, fallbackProvider] in
            var delivered = false
            do {
                // The first list shows right away; later lists replace it as the
                // service analyzes more candidate songs.
                for try await songs in primaryProvider.similarUpdates(to: song) {
                    guard deliver(songs, for: song, isFirst: !delivered) else { return }
                    delivered = true
                    isRefining = true
                }
            } catch {
                // Service down, missing key, bad JSON, refusal… handled below.
            }
            isRefining = false
            guard !delivered, !Task.isCancelled else { return }
            let songs = (try? await fallbackProvider.similar(to: song)) ?? []
            _ = deliver(songs, for: song, isFirst: true)
        }
    }

    /// Shows `songs` if the sheet is still open on `song`; returns false otherwise.
    private func deliver(_ songs: [Song], for song: Song, isFirst: Bool) -> Bool {
        // Discard results if the sheet was dismissed or the selection changed meanwhile.
        guard !Task.isCancelled, isSheetPresented, selectedSong?.id == song.id else { return false }
        isLoading = false
        results = songs
        sheetMode = .results
        if isFirst { resultsCount += 1 }
        return true
    }

    private func cancelSimilarSearch() {
        similarTask?.cancel()
        similarTask = nil
        isLoading = false
        isRefining = false
        player.stop()
    }
}

#if DEBUG
extension SearchViewModel {
    /// A view model with the sheet already open, for previews.
    static func preview(mode: SheetMode, song: Song = Catalog.songs[0]) -> SearchViewModel {
        let model = SearchViewModel()
        model.selectedSong = song
        model.isSheetPresented = true
        model.sheetMode = mode
        if mode == .results {
            model.results = LocalSimilarSongs().ranked(for: song)
        }
        return model
    }
}
#endif
