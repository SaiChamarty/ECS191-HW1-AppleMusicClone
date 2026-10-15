import SwiftUI

/// Playlists tab: a "New Playlist…" row followed by the user's playlists.
struct PlaylistsView: View {
    @Environment(PlaylistStore.self) private var playlists

    var body: some View {
        NavigationStack {
            List {
                header
                    .listRowSeparator(.hidden)
                    .themedRow()

                Button {
                    playlists.requestNewPlaylist()
                } label: {
                    HStack(spacing: 16) {
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Theme.surface)
                            .frame(width: 72, height: 72)
                            .overlay {
                                Image(systemName: "plus")
                                    .font(.system(size: 30, weight: .light))
                                    .foregroundStyle(Theme.accent)
                            }
                        Text("New Playlist…")
                            .font(.archivo(.regular, size: 17, relativeTo: .body))
                            .foregroundStyle(Theme.accent)
                        Spacer(minLength: 0)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(RowButtonStyle())
                .themedRow()

                ForEach(playlists.playlists) { playlist in
                    NavigationLink(value: playlist.id) {
                        PlaylistRow(playlist: playlist)
                    }
                    .contextMenu {
                        Button("Delete Playlist", systemImage: "trash", role: .destructive) {
                            playlists.delete(playlist.id)
                        }
                    }
                    .themedRow()
                }
                .onDelete { playlists.delete(at: $0) }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Theme.background)
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: Playlist.ID.self) { id in
                PlaylistDetailView(playlistID: id)
            }
        }
    }

    /// Matches the Home tab's header.
    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Kicker("SoundAlike")
            Text("Playlists")
                .font(.archivo(.extraBold, size: 34, relativeTo: .largeTitle))
                .tracking(34 * -0.02)
                .foregroundStyle(Theme.ink)
                .accessibilityAddTraits(.isHeader)
        }
        .padding(.bottom, 4)
    }
}

private struct PlaylistRow: View {
    let playlist: Playlist

    var body: some View {
        HStack(spacing: 16) {
            PlaylistArtwork(playlist: playlist, size: 72)
            VStack(alignment: .leading, spacing: 3) {
                Text(playlist.name)
                    .font(.archivo(.medium, size: 17, relativeTo: .body))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                Text(playlist.songCountText)
                    .font(.archivo(.regular, size: 13, relativeTo: .footnote))
                    .foregroundStyle(Theme.secondaryText)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// The first song's artwork, or a music-note tile for an empty playlist.
struct PlaylistArtwork: View {
    let playlist: Playlist
    let size: CGFloat

    var body: some View {
        if let first = playlist.songs.first {
            ArtworkTile(song: first, size: size)
        } else {
            RoundedRectangle(cornerRadius: size >= 80 ? 10 : 6, style: .continuous)
                .fill(Theme.surface)
                .frame(width: size, height: size)
                .overlay {
                    Image(systemName: "music.note.list")
                        .font(.system(size: size * 0.36, weight: .regular))
                        .foregroundStyle(Theme.ink.opacity(0.35))
                }
                .accessibilityHidden(true)
        }
    }
}

// MARK: - Detail

struct PlaylistDetailView: View {
    let playlistID: Playlist.ID

    @Environment(PlaylistStore.self) private var playlists
    @Environment(SearchViewModel.self) private var viewModel
    @Environment(\.dismiss) private var dismiss
    @State private var isRenaming = false
    @State private var isConfirmingDelete = false
    @State private var draftName = ""

    var body: some View {
        if let playlist = playlists.playlist(id: playlistID) {
            List {
                header(for: playlist)
                    .listRowSeparator(.hidden)
                    .themedRow()

                if playlist.songs.isEmpty {
                    VStack(spacing: 6) {
                        Text("No songs yet")
                            .font(.archivo(.semibold, size: 16, relativeTo: .body))
                        Text("Tap ••• on any song and choose Add to Playlist.")
                            .font(.archivo(.regular, size: 14, relativeTo: .subheadline))
                            .foregroundStyle(Theme.secondaryText)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
                    .listRowSeparator(.hidden)
                    .themedRow()
                }

                ForEach(playlist.songs) { song in
                    PlaylistSongRow(song: song, player: viewModel.player) {
                        viewModel.select(song)
                    } onRemove: {
                        playlists.removeSong(song, from: playlistID)
                    }
                    .contextMenu {
                        SongActions(song: song) {
                            viewModel.findSimilar(to: song)
                        } onRemove: {
                            playlists.removeSong(song, from: playlistID)
                        }
                    }
                    .themedRow()
                }
                .onDelete { playlists.removeSongs(at: $0, from: playlistID) }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Theme.background)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("Rename", systemImage: "pencil") {
                            draftName = playlist.name
                            isRenaming = true
                        }
                        Button("Delete Playlist", systemImage: "trash", role: .destructive) {
                            isConfirmingDelete = true
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                    .accessibilityLabel("Playlist actions")
                }
            }
            .alert("Rename Playlist", isPresented: $isRenaming) {
                TextField("Playlist Name", text: $draftName)
                Button("Cancel", role: .cancel) {}
                Button("Save") { playlists.rename(playlistID, to: draftName) }
            }
            .confirmationDialog("Delete “\(playlist.name)”?", isPresented: $isConfirmingDelete, titleVisibility: .visible) {
                Button("Delete Playlist", role: .destructive) {
                    dismiss()
                    playlists.delete(playlistID)
                }
            }
        } else {
            ContentUnavailableView("Playlist Not Found", systemImage: "music.note.list")
        }
    }

    private func header(for playlist: Playlist) -> some View {
        VStack(spacing: 10) {
            PlaylistArtwork(playlist: playlist, size: 200)
                .shadow(color: Theme.ink.opacity(0.12), radius: 12, y: 6)
            Text(playlist.name)
                .font(.archivo(.extraBold, size: 24, relativeTo: .title2))
                .foregroundStyle(Theme.ink)
                .multilineTextAlignment(.center)
            Text(playlist.songCountText)
                .font(.archivo(.regular, size: 14, relativeTo: .subheadline))
                .foregroundStyle(Theme.secondaryText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
    }
}

private struct PlaylistSongRow: View {
    let song: Song
    let player: PreviewPlayer
    let action: () -> Void
    let onRemove: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            Button(action: action) {
                HStack(spacing: 12) {
                    ArtworkTile(song: song, size: 48)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(song.title)
                            .font(.archivo(.semibold, size: 16, relativeTo: .body))
                            .foregroundStyle(Theme.ink)
                        Text(song.artistAndYear)
                            .font(.archivo(.regular, size: 13, relativeTo: .footnote))
                            .foregroundStyle(Theme.secondaryText)
                    }
                    .multilineTextAlignment(.leading)
                    Spacer(minLength: 8)
                }
                .padding(.vertical, 4)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle())
            .accessibilityElement(children: .combine)

            if song.previewURL != nil {
                PreviewButton(song: song, player: player)
            }
            SongActionsMenu(song: song, onRemove: onRemove)
        }
    }
}

private extension View {
    /// App background and hairline separators for rows in a plain `List`.
    func themedRow() -> some View {
        listRowBackground(Theme.background)
            .listRowSeparatorTint(Theme.hairline)
            .listRowInsets(EdgeInsets(top: 8, leading: 20, bottom: 8, trailing: 12))
    }
}
