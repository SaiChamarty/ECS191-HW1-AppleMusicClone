import SwiftUI

/// The actions available on any song: Find Similar Songs and Add to Playlist.
/// Used as the "•••" menu on every song row and as its long-press context menu.
struct SongActions: View {
    let song: Song
    /// Overrides the default find-similar behavior (e.g. from a results list).
    var onFindSimilar: (() -> Void)?
    /// Shown as "Remove from Playlist" when the song is listed inside a playlist.
    var onRemove: (() -> Void)?

    @Environment(SearchViewModel.self) private var viewModel
    @Environment(PlaylistStore.self) private var playlists

    var body: some View {
        Button("Find Similar Songs", systemImage: "waveform") {
            if let onFindSimilar {
                onFindSimilar()
            } else {
                viewModel.findSimilar(to: song)
            }
        }

        Menu("Add to Playlist", systemImage: "text.badge.plus") {
            Button("New Playlist…", systemImage: "plus") {
                playlists.requestNewPlaylist(adding: song)
            }
            if !playlists.playlists.isEmpty {
                Divider()
            }
            ForEach(playlists.playlists) { playlist in
                Button(playlist.name) {
                    playlists.add(song, to: playlist.id)
                }
            }
        }

        if let onRemove {
            Divider()
            Button("Remove from Playlist", systemImage: "minus.circle", role: .destructive, action: onRemove)
        }
    }
}

/// "•••" button that opens `SongActions`.
struct SongActionsMenu: View {
    let song: Song
    var onFindSimilar: (() -> Void)?
    var onRemove: (() -> Void)?

    var body: some View {
        Menu {
            SongActions(song: song, onFindSimilar: onFindSimilar, onRemove: onRemove)
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Theme.ink.opacity(0.6))
                .frame(width: 36, height: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("More actions")
        .accessibilityValue("\(song.title), \(song.artist)")
    }
}
