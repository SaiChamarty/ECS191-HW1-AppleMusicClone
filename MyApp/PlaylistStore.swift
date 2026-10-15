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
}

/// Asks the root view to prompt for a new playlist's name; `song` is added once it's created.
struct NewPlaylistRequest: Identifiable, Equatable {
    let id = UUID()
    let song: Song?
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

    func requestNewPlaylist(adding song: Song? = nil) {
        newPlaylistRequest = NewPlaylistRequest(song: song)
    }

    @discardableResult
    func createPlaylist(named name: String, adding song: Song? = nil) -> Playlist {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let playlist = Playlist(name: trimmed.isEmpty ? "New Playlist" : trimmed, songs: song.map { [$0] } ?? [])
        // Newest first, like Apple Music's recently added order.
        playlists.insert(playlist, at: 0)
        save()
        if song != nil {
            addedCount += 1
            show("Added to \(playlist.name)")
        }
        return playlist
    }

    func add(_ song: Song, to playlistID: Playlist.ID) {
        guard let index = playlists.firstIndex(where: { $0.id == playlistID }) else { return }
        let name = playlists[index].name
        if playlists[index].songs.contains(where: { $0.id == song.id }) {
            show("Already in \(name)")
            return
        }
        // Store the plain song; the similarity "why" line belongs to one search.
        var stored = song
        stored.why = nil
        playlists[index].songs.append(stored)
        save()
        addedCount += 1
        show("Added to \(name)")
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
