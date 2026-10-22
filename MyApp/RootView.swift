import SwiftUI

/// Tab bar (Home, Playlists) plus app-wide UI shared by both tabs: the
/// similar-songs sheet, the "New Playlist" name prompt, and confirmations.
///
/// A standard `TabView` gets the floating Liquid Glass tab bar automatically
/// on iOS 26 and later, and the classic tab bar on earlier versions.
struct RootView: View {
    enum TabID: Hashable {
        case home
        case playlists
    }

    @State private var selection: TabID = .home
    @State private var viewModel: SearchViewModel
    @State private var playlists: PlaylistStore
    /// The request being named in the alert (kept while the alert dismisses).
    @State private var pendingRequest: NewPlaylistRequest?
    @State private var newPlaylistName = ""

    init(viewModel: SearchViewModel = SearchViewModel(), playlists: PlaylistStore = PlaylistStore()) {
        _viewModel = State(initialValue: viewModel)
        _playlists = State(initialValue: playlists)
    }

    var body: some View {
        TabView(selection: $selection) {
            ContentView(viewModel: viewModel)
                .tabItem { Label("Home", systemImage: "house") }
                .tag(TabID.home)

            PlaylistsView()
                .tabItem { Label("Playlists", systemImage: "music.note.square.stack") }
                .tag(TabID.playlists)
        }
        .tint(Theme.accent)
        .environment(viewModel)
        .environment(playlists)
        // Above the tabs so "Find Similar Songs" works from any tab.
        .overlay {
            SongSheet(viewModel: viewModel)
                .environment(viewModel)
                .environment(playlists)
        }
        .overlay(alignment: .top) {
            if let toast = playlists.toast {
                ToastView(message: toast)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.34, dampingFraction: 0.85), value: playlists.toast)
        .onChange(of: playlists.newPlaylistRequest) { _, request in
            if let request {
                pendingRequest = request
                newPlaylistName = request.suggestedName
            }
        }
        .alert("New Playlist", isPresented: isNamingPlaylist) {
            TextField("Playlist Name", text: $newPlaylistName)
            Button("Cancel", role: .cancel) {}
            Button("Create") {
                playlists.createPlaylist(named: newPlaylistName, adding: pendingRequest?.songs ?? [])
            }
        } message: {
            if let songs = pendingRequest?.songs, let first = songs.first {
                Text(songs.count == 1 ? "“\(first.title)” will be added to it." : "\(songs.count) songs will be added to it.")
            }
        }
        .sensoryFeedback(.impact(weight: .light), trigger: viewModel.selectionCount)
        .sensoryFeedback(.success, trigger: viewModel.resultsCount)
        .sensoryFeedback(.success, trigger: playlists.addedCount)
        .preferredColorScheme(.light)
    }

    private var isNamingPlaylist: Binding<Bool> {
        Binding(
            get: { playlists.newPlaylistRequest != nil },
            set: { if !$0 { playlists.newPlaylistRequest = nil } }
        )
    }
}

/// Brief confirmation capsule, e.g. "Added to Road Trip".
private struct ToastView: View {
    let message: String

    var body: some View {
        Label(message, systemImage: "checkmark.circle.fill")
            .font(.archivo(.semibold, size: 14, relativeTo: .subheadline))
            .foregroundStyle(Theme.ink)
            .symbolRenderingMode(.multicolor)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Capsule().fill(.ultraThinMaterial))
            .overlay(Capsule().strokeBorder(Color.white.opacity(0.75), lineWidth: 1))
            .shadow(color: Theme.ink.opacity(0.12), radius: 12, y: 6)
            .accessibilityAddTraits(.updatesFrequently)
    }
}

#Preview("App") {
    RootView(playlists: PlaylistStore(fileURL: nil))
}

#Preview("Playlists tab") {
    let store = PlaylistStore(fileURL: nil)
    let playlist = store.createPlaylist(named: "Late Night Drive")
    for song in Catalog.songs.prefix(4) {
        store.add(song, to: playlist.id)
    }
    store.createPlaylist(named: "Empty Playlist")
    return PlaylistsView()
        .environment(SearchViewModel())
        .environment(store)
}
