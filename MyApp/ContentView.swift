import SwiftUI

/// Home tab: search plus popular songs. The similar-songs sheet lives in `RootView`.
struct ContentView: View {
    @Bindable var viewModel: SearchViewModel
    @FocusState private var isFieldFocused: Bool
    /// Bottom edge of the search field in the root coordinate space; anchors the dropdown.
    @State private var fieldBottom: CGFloat = 0

    private static let rootSpace = "root"

    var body: some View {
        ZStack(alignment: .top) {
            Theme.background.ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header

                    SearchField(
                        query: $viewModel.query,
                        isFocused: $isFieldFocused,
                        onClear: viewModel.clearQuery
                    )
                    .padding(.top, 14)
                    .onGeometryChange(for: CGFloat.self) { proxy in
                        proxy.frame(in: .named(Self.rootSpace)).maxY
                    } action: { newValue in
                        fieldBottom = newValue
                    }

                    popularSection
                        .padding(.top, 28)
                }
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, 40)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.immediately)

            if viewModel.showsDropdown {
                SearchDropdown(viewModel: viewModel)
                    // Extends 8pt past the field (20pt side padding) on each side.
                    .padding(.horizontal, 12)
                    .padding(.top, max(fieldBottom + 8, 8))
                    .padding(.bottom, 12)
                    .transition(.opacity.combined(with: .scale(scale: 0.98, anchor: .top)))
            }
        }
        .coordinateSpace(.named(Self.rootSpace))
        .animation(.easeOut(duration: 0.18), value: viewModel.showsDropdown)
        .foregroundStyle(Theme.ink)
        .accessibilityHidden(viewModel.isSheetPresented)
        .task { await viewModel.loadPopular() }
        .task(id: viewModel.query) { await viewModel.refreshMatches() }
        .onChange(of: isFieldFocused) { _, focused in
            viewModel.isSearchFocused = focused
        }
        .onChange(of: viewModel.isSearchFocused) { _, focused in
            if isFieldFocused != focused { isFieldFocused = focused }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Kicker("SoundAlike")
            Text("Find Similar Songs")
                .font(.archivo(.extraBold, size: 34, relativeTo: .largeTitle))
                .tracking(34 * -0.02)
                .accessibilityAddTraits(.isHeader)
            Text("Search for a song you love and we’ll find 10 more with the same vibe.")
                .font(.archivo(.regular, size: 15, relativeTo: .subheadline))
                .foregroundStyle(Theme.secondaryText)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 2)
        }
    }

    private var popularSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Popular searches".uppercased())
                .font(.archivo(.extraBold, size: 13, relativeTo: .footnote))
                .tracking(13 * 0.08)
                .accessibilityAddTraits(.isHeader)
                .padding(.bottom, 8)

            Rectangle()
                .fill(Theme.ink)
                .frame(height: 2)

            if viewModel.popular.isEmpty {
                // The chart loads in a moment; offline it falls back to the bundled list.
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
                    .accessibilityLabel("Loading popular songs")
            }

            ForEach(viewModel.popular) { song in
                if song.id != viewModel.popular.first?.id {
                    Hairline()
                }
                PopularRow(song: song, player: viewModel.player) {
                    viewModel.select(song)
                }
                .contextMenu {
                    SongActions(song: song)
                }
            }
        }
    }
}

// MARK: - Popular row

private struct PopularRow: View {
    let song: Song
    let player: PreviewPlayer
    let action: () -> Void

    var body: some View {
        HStack(spacing: 4) {
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
                .padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(RowButtonStyle())
            .accessibilityElement(children: .combine)

            // Preview first, then tap the row (or •••) to find similar songs.
            if song.previewURL != nil {
                PreviewButton(song: song, player: player)
            }
            SongActionsMenu(song: song)
        }
    }
}

// MARK: - Search field

private struct SearchField: View {
    @Binding var query: String
    var isFocused: FocusState<Bool>.Binding
    let onClear: () -> Void

    var body: some View {
        let focused = isFocused.wrappedValue
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Theme.ink.opacity(0.6))
                .accessibilityHidden(true)

            TextField(
                "Search a song or artist",
                text: $query,
                prompt: Text("Search a song or artist").foregroundStyle(Theme.ink.opacity(0.45))
            )
            .font(.archivo(.regular, size: 16, relativeTo: .body))
            .foregroundStyle(Theme.ink)
            .tint(Theme.accent)
            .focused(isFocused)
            .submitLabel(.search)
            .autocorrectionDisabled()
            .textInputAutocapitalization(.never)

            if !query.isEmpty {
                Button(action: onClear) {
                    Image(systemName: "xmark")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 20, height: 20)
                        .background(Circle().fill(Theme.ink.opacity(0.5)))
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, query.isEmpty ? 14 : 6)
        .frame(minHeight: 44)
        .background {
            ZStack {
                Capsule().fill(.ultraThinMaterial)
                Capsule().fill(Color.white.opacity(0.72))
            }
        }
        .overlay {
            Capsule().strokeBorder(Theme.ink.opacity(0.08), lineWidth: 1)
        }
        .overlay {
            // 3pt accent-300 ring drawn just outside the capsule.
            Capsule()
                .inset(by: -1.5)
                .stroke(Theme.accent300, lineWidth: 3)
                .opacity(focused ? 1 : 0)
        }
        .shadow(
            color: Theme.ink.opacity(focused ? 0.10 : 0.06),
            radius: focused ? 10 : 5,
            y: focused ? 6 : 2
        )
        .contentShape(Capsule())
        .onTapGesture { isFocused.wrappedValue = true }
        .animation(.easeOut(duration: 0.18), value: focused)
    }
}

// MARK: - Dropdown

private struct SearchDropdown: View {
    var viewModel: SearchViewModel
    @State private var contentHeight: CGFloat = 0

    private static let shape = RoundedRectangle(cornerRadius: 18, style: .continuous)

    var body: some View {
        // Hugs its content; once taller than 600pt (or the space above the
        // keyboard) it scrolls internally.
        ScrollView {
            content
                .onGeometryChange(for: CGFloat.self) { proxy in
                    proxy.size.height
                } action: { newValue in
                    contentHeight = newValue
                }
        }
        .scrollIndicators(.hidden)
        .scrollBounceBehavior(.basedOnSize)
        .scrollDismissesKeyboard(.immediately)
        .frame(maxHeight: min(contentHeight, 600))
        .background {
            ZStack {
                Self.shape.fill(.ultraThinMaterial)
                Self.shape.fill(Color.white.opacity(0.58))
            }
        }
        .clipShape(Self.shape)
        .overlay {
            Self.shape.strokeBorder(Color.white.opacity(0.75), lineWidth: 1)
        }
        .shadow(color: Theme.ink.opacity(0.18), radius: 24, y: 14)
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(viewModel.suggestions, id: \.self) { suggestion in
                Button {
                    viewModel.applySuggestion(suggestion)
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(Theme.ink.opacity(0.55))
                            .accessibilityHidden(true)
                        Text(highlighted(suggestion, matching: viewModel.trimmedQuery))
                            .lineLimit(1)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 11)
                    .contentShape(Rectangle())
                }
                .buttonStyle(RowButtonStyle())
                .accessibilityLabel(suggestion)
                .accessibilityHint("Searches for this")
            }

            Hairline()
                .padding(.vertical, 4)

            if viewModel.matches.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("No songs match “\(viewModel.trimmedQuery)”.")
                        .font(.archivo(.medium, size: 15, relativeTo: .body))
                    Text("Try an artist name or part of a title.")
                        .font(.archivo(.regular, size: 13, relativeTo: .footnote))
                        .foregroundStyle(Theme.secondaryText)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
            } else {
                ForEach(viewModel.matches) { song in
                    if song.id != viewModel.matches.first?.id {
                        Hairline().padding(.leading, 16)
                    }
                    HStack(spacing: 0) {
                        Button {
                            viewModel.select(song)
                        } label: {
                            HStack(spacing: 12) {
                                ArtworkTile(song: song, size: 48)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(song.title)
                                        .font(.archivo(.medium, size: 16, relativeTo: .body))
                                        .foregroundStyle(Theme.ink)
                                    Text("Song · \(song.artist)")
                                        .font(.archivo(.regular, size: 13, relativeTo: .footnote))
                                        .foregroundStyle(Theme.secondaryText)
                                }
                                .multilineTextAlignment(.leading)
                                Spacer(minLength: 0)
                            }
                            .padding(.leading, 16)
                            .padding(.trailing, 8)
                            .padding(.vertical, 8)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(RowButtonStyle())
                        .accessibilityElement(children: .combine)
                        .contextMenu {
                            SongActions(song: song)
                        }

                        if song.previewURL != nil {
                            PreviewButton(song: song, player: viewModel.player)
                        }
                        SongActionsMenu(song: song)
                            .padding(.trailing, 4)
                    }
                }
            }
        }
        .padding(.vertical, 6)
    }

    /// The part of `text` matching `query` in full ink + medium weight; the rest at 55% ink.
    private func highlighted(_ text: String, matching query: String) -> AttributedString {
        var result = AttributedString(text)
        result.font = .archivo(.regular, size: 16, relativeTo: .body)
        result.foregroundColor = Theme.ink.opacity(0.55)
        guard !query.isEmpty,
              let range = result.range(of: query, options: [.caseInsensitive, .diacriticInsensitive])
        else { return result }
        result[range].font = .archivo(.medium, size: 16, relativeTo: .body)
        result[range].foregroundColor = Theme.ink
        return result
    }
}

#Preview {
    RootView(playlists: PlaylistStore(fileURL: nil))
}

#Preview("Searching") {
    let model = SearchViewModel()
    model.query = "fr"
    return RootView(viewModel: model, playlists: PlaylistStore(fileURL: nil))
}
