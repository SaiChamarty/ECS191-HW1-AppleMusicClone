import Foundation
import MediaPlayer

/// Copies a SoundAlike playlist into the user's Apple Music library.
///
/// Uses MediaPlayer's app-maintained playlists, which work with a free developer
/// account (unlike MusicKit's catalog APIs). Song `trackID`s come from the
/// iTunes catalog and double as Apple Music product IDs.
enum AppleMusicExporter {
    struct Result {
        let added: Int
        /// Songs with no catalog ID, or that Apple Music couldn't add.
        let skipped: Int
    }

    enum ExportError: LocalizedError {
        case notAuthorized
        case nothingToAdd
        case couldNotCreatePlaylist

        var errorDescription: String? {
            switch self {
            case .notAuthorized:
                "SoundAlike needs access to your Apple Music library. You can allow it in Settings › Apps › SoundAlike."
            case .nothingToAdd:
                "None of the songs in this playlist could be found in Apple Music."
            case .couldNotCreatePlaylist:
                "Apple Music couldn't create the playlist. Make sure you're signed in to Apple Music with an active subscription."
            }
        }
    }

    /// Opens the Music app.
    static let musicAppURL = URL(string: "music://")!

    static func export(_ playlist: Playlist) async throws -> Result {
        guard await requestAuthorization() == .authorized else { throw ExportError.notAuthorized }

        let productIDs = playlist.songs.compactMap { $0.trackID.map(String.init) }
        guard !productIDs.isEmpty else { throw ExportError.nothingToAdd }

        // Keyed by our playlist's UUID, so exporting again updates the same Apple Music playlist.
        let metadata = MPMediaPlaylistCreationMetadata(name: playlist.name)
        metadata.descriptionText = "Made with SoundAlike"
        let appleMusicPlaylist: MPMediaPlaylist
        do {
            appleMusicPlaylist = try await MPMediaLibrary.default().getPlaylist(with: playlist.id, creationMetadata: metadata)
        } catch {
            throw ExportError.couldNotCreatePlaylist
        }

        // Skip songs already in the Apple Music playlist from an earlier export.
        let existing = Set(appleMusicPlaylist.items.map(\.playbackStoreID))
        var added = 0
        var failed = 0
        for productID in productIDs where !existing.contains(productID) {
            do {
                try await appleMusicPlaylist.addItem(withProductID: productID)
                added += 1
            } catch {
                failed += 1
            }
        }

        let alreadyThere = productIDs.count - added - failed
        if added + alreadyThere == 0 { throw ExportError.nothingToAdd }
        return Result(added: added, skipped: playlist.songs.count - productIDs.count + failed)
    }

    private static func requestAuthorization() async -> MPMediaLibraryAuthorizationStatus {
        let status = MPMediaLibrary.authorizationStatus()
        guard status == .notDetermined else { return status }
        return await withCheckedContinuation { continuation in
            MPMediaLibrary.requestAuthorization { continuation.resume(returning: $0) }
        }
    }
}
