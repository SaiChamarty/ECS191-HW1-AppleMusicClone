import Foundation
import Observation
import SwiftUI  // IndexSet-based remove(atOffsets:) for List deletes

struct Playlist: Identifiable, Codable, Hashable {
    let id: UUID
    var name: String
    var songs: [Song]
    let createdAt: Date

    init(name: String, songs: [Song] = []) {
        self.id = UUID()
        self.name = name
        self.songs = songs
        self.createdAt = .now
    }

    var songCountText: String {
        songs.count == 1 ? "1 song" : "\(songs.count) songs"
    }

    /// Plain-text track list for the share sheet, with an Apple Music link per song
    /// so friends without the app can open each one.
    var shareText: String {
        let tracks = songs.enumerated().map { index, song in
            var line = "\(index + 1). \(song.title) – \(song.artist)"
            if let trackID = song.trackID {
                line += "\n   https://music.apple.com/\(ITunesCatalog.storefront)/song/\(trackID)"
            }
            return line
        }
        return (["🎧 \(name) (\(songCountText))", ""] + tracks + ["", "Made with SoundAlike"])
            .joined(separator: "\n")
    }
}

/// Asks the root view to prompt for a new playlist's name; `songs` are added once it's created.
struct NewPlaylistRequest: Identifiable, Equatable {
    let id = UUID()
    let songs: [Song]
    /// Pre-filled in the name field (e.g. "Songs like Midnight City").
    var suggestedName = ""
}

/// The user's playlists, saved as JSON in Application Support.
@Observable
final class PlaylistStore {
    private(set) var playlists: [Playlist] = []
    var newPlaylistRequest: NewPlaylistRequest?
    /// Short confirmation shown after adding a song ("Added to Road Trip").
    private(set) var toast: String?
    /// Incremented when a song is added; drives haptic feedback.
    private(set) var addedCount = 0

    @ObservationIgnored private let fileURL: URL?
    @ObservationIgnored private var toastTask: Task<Void, Never>?

    /// Pass `nil` for an in-memory store (previews).
    init(fileURL: URL? = PlaylistStore.defaultFileURL) {
        self.fileURL = fileURL
        load()
    }

    static var defaultFileURL: URL? {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appending(path: "playlists.json")
    }

    func playlist(id: Playlist.ID) -> Playlist? {
        playlists.first { $0.id == id }
    }

    // MARK: Editing

    func requestNewPlaylist(adding songs: [Song] = [], suggestedName: String = "") {
        newPlaylistRequest = NewPlaylistRequest(songs: songs, suggestedName: suggestedName)
    }

    @discardableResult
    func createPlaylist(named name: String, adding songs: [Song] = []) -> Playlist {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        var unique = Set<Song.ID>()
        let stored = songs.filter { unique.insert($0.id).inserted }.map(Self.stored)
        let playlist = Playlist(name: trimmed.isEmpty ? "New Playlist" : trimmed, songs: stored)
        // Newest first, like Apple Music's recently added order.
        playlists.insert(playlist, at: 0)
        save()
        if !stored.isEmpty {
            addedCount += 1
            show(stored.count == 1 ? "Added to \(playlist.name)" : "Added \(stored.count) songs to \(playlist.name)")
        }
        return playlist
    }

    func add(_ song: Song, to playlistID: Playlist.ID) {
        add([song], to: playlistID)
    }

    /// Appends the songs not already in the playlist, keeping their order.
    func add(_ songs: [Song], to playlistID: Playlist.ID) {
        guard let index = playlists.firstIndex(where: { $0.id == playlistID }) else { return }
        let name = playlists[index].name
        var present = Set(playlists[index].songs.map(\.id))
        let new = songs.filter { present.insert($0.id).inserted }.map(Self.stored)
        guard !new.isEmpty else {
            show(songs.count == 1 ? "Already in \(name)" : "All already in \(name)")
            return
        }
        playlists[index].songs.append(contentsOf: new)
        save()
        addedCount += 1
        show(new.count == 1 ? "Added to \(name)" : "Added \(new.count) songs to \(name)")
    }

    /// The plain song; the similarity "why" line belongs to one search.
    private static func stored(_ song: Song) -> Song {
        var stored = song
        stored.why = nil
        return stored
    }

    func removeSong(_ song: Song, from playlistID: Playlist.ID) {
        guard let index = playlists.firstIndex(where: { $0.id == playlistID }) else { return }
        playlists[index].songs.removeAll { $0.id == song.id }
        save()
    }

    func removeSongs(at offsets: IndexSet, from playlistID: Playlist.ID) {
        guard let index = playlists.firstIndex(where: { $0.id == playlistID }) else { return }
        playlists[index].songs.remove(atOffsets: offsets)
        save()
    }

    func rename(_ playlistID: Playlist.ID, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let index = playlists.firstIndex(where: { $0.id == playlistID }) else { return }
        playlists[index].name = trimmed
        save()
    }

    func delete(_ playlistID: Playlist.ID) {
        playlists.removeAll { $0.id == playlistID }
        save()
    }

    func delete(at offsets: IndexSet) {
        playlists.remove(atOffsets: offsets)
        save()
    }

    // MARK: Persistence

    private func load() {
        guard let fileURL, let data = try? Data(contentsOf: fileURL) else { return }
        playlists = (try? JSONDecoder().decode([Playlist].self, from: data)) ?? []
    }

    private func save() {
        guard let fileURL else { return }
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(playlists).write(to: fileURL, options: .atomic)
        } catch {
            print("Couldn't save playlists: \(error)")
        }
    }

    private func show(_ message: String) {
        toast = message
        toastTask?.cancel()
        toastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled else { return }
            self?.toast = nil
        }
    }
}
