import SwiftUI

/// Custom translucent bottom sheet. Built as an overlay (not `.sheet`) so it
/// can blur the content behind it and resize between confirm and results.
struct SongSheet: View {
    var viewModel: SearchViewModel

    @State private var dragOffset: CGFloat = 0

    private static let slide = Animation.spring(response: 0.34, dampingFraction: 0.85)
    private static let shape = UnevenRoundedRectangle(topLeadingRadius: 28, topTrailingRadius: 28, style: .continuous)

    var body: some View {
        GeometryReader { proxy in
            let bottomInset = proxy.safeAreaInsets.bottom
            // Full height of the layer once it extends under the bottom safe area.
            let layerHeight = proxy.size.height + bottomInset

            ZStack(alignment: .bottom) {
                if viewModel.isSheetPresented {
                    Theme.ink.opacity(0.22)
                        .onTapGesture { viewModel.dismissSheet() }
                        .accessibilityLabel("Dismiss")
                        .accessibilityAddTraits(.isButton)
                        .transition(.opacity.animation(.easeOut(duration: 0.26)))

                    panel(bottomInset: bottomInset, resultsHeight: layerHeight - 64)
                        .offset(y: dragOffset)
                        .gesture(dismissDrag)
                        .transition(.move(edge: .bottom).animation(Self.slide))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
            .ignoresSafeArea(.container, edges: .bottom)
        }
        .ignoresSafeArea(.keyboard)
        .animation(Self.slide, value: viewModel.isSheetPresented)
        .animation(Self.slide, value: viewModel.sheetMode)
        .onChange(of: viewModel.isSheetPresented) { _, isPresented in
            if isPresented { dragOffset = 0 }
        }
    }

    // MARK: Panel

    private func panel(bottomInset: CGFloat, resultsHeight: CGFloat) -> some View {
        VStack(spacing: 0) {
            Capsule()
                .fill(Theme.ink.opacity(0.22))
                .frame(width: 36, height: 5)
                .padding(.top, 8)
                .padding(.bottom, 14)
                .accessibilityHidden(true)

            if let song = viewModel.selectedSong {
                switch viewModel.sheetMode {
                case .confirm:
                    ConfirmContent(song: song, viewModel: viewModel)
                        .transition(.opacity)
                case .results:
                    ResultsContent(song: song, viewModel: viewModel)
                        .transition(.opacity)
                }
            }
        }
        .padding(.bottom, bottomInset)
        .frame(maxWidth: .infinity)
        .frame(height: viewModel.sheetMode == .results ? resultsHeight : nil, alignment: .top)
        .background {
            ZStack {
                Self.shape.fill(.ultraThinMaterial)
                Self.shape.fill(Theme.sheetTint.opacity(0.62))
            }
            .shadow(color: Theme.ink.opacity(0.16), radius: 20, y: -10)
        }
        .overlay {
            // 1pt white top border that fades out down the rounded sides.
            Self.shape
                .strokeBorder(Color.white.opacity(0.8), lineWidth: 1)
                .mask(alignment: .top) {
                    LinearGradient(colors: [.white, .clear], startPoint: .top, endPoint: .bottom)
                        .frame(height: 40)
                }
        }
        .foregroundStyle(Theme.ink)
        .accessibilityAddTraits(.isModal)
    }

    /// Drag down to dismiss; resists upward drags.
    private var dismissDrag: some Gesture {
        DragGesture(minimumDistance: 6)
            .onChanged { value in
                let y = value.translation.height
                dragOffset = y > 0 ? y : y / 6
            }
            .onEnded { value in
                if value.translation.height > 120 || value.predictedEndTranslation.height > 260 {
                    viewModel.dismissSheet()
                } else {
                    withAnimation(Self.slide) { dragOffset = 0 }
                }
            }
    }
}

// MARK: - Confirm mode

private struct ConfirmContent: View {
    let song: Song
    var viewModel: SearchViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                ArtworkTile(song: song, size: 92)
                VStack(alignment: .leading, spacing: 4) {
                    Kicker("Selected")
                    Text(song.title)
                        .font(.archivo(.extraBold, size: 22, relativeTo: .title2))
                        .lineLimit(2)
                    Text(song.artistAndYear)
                        .font(.archivo(.regular, size: 14, relativeTo: .subheadline))
                        .foregroundStyle(Theme.secondaryText)
                }
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .combine)
            .padding(.bottom, 18)

            Hairline()

            Text("Find more songs like this song?")
                .font(.archivo(.extraBold, size: 20, relativeTo: .title3))
                .padding(.top, 18)

            Text("We’ll match its sound, mood and era to 10 other tracks.")
                .font(.archivo(.regular, size: 14, relativeTo: .subheadline))
                .foregroundStyle(Theme.ink.opacity(0.7))
                .padding(.top, 6)

            Button {
                viewModel.findSimilar()
            } label: {
                HStack {
                    Text(viewModel.isLoading ? "Finding 10 songs…" : "Find 10 similar songs")
                    Spacer(minLength: 8)
                    Image(systemName: "arrow.right")
                }
                .font(.archivo(.extraBold, size: 16, relativeTo: .headline))
                .foregroundStyle(Theme.background)
                .padding(.horizontal, 22)
                .frame(maxWidth: .infinity, minHeight: 52)
            }
            .buttonStyle(PrimaryCapsuleButtonStyle(isLoading: viewModel.isLoading))
            .disabled(viewModel.isLoading)
            .padding(.top, 22)

            Button {
                viewModel.dismissSheet()
            } label: {
                HStack {
                    Text("Cancel")
                    Spacer(minLength: 0)
                }
                .font(.archivo(.medium, size: 15, relativeTo: .body))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 22)
                .frame(maxWidth: .infinity, minHeight: 48)
            }
            .buttonStyle(SecondaryCapsuleButtonStyle())
            .padding(.top, 10)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 12)
    }
}

// MARK: - Results mode

private struct ResultsContent: View {
    let song: Song
    var viewModel: SearchViewModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Kicker("\(viewModel.results.count) songs like")
                    Text(song.title)
                        .font(.archivo(.extraBold, size: 24, relativeTo: .title2))
                    Text(song.artist)
                        .font(.archivo(.regular, size: 14, relativeTo: .subheadline))
                        .foregroundStyle(Theme.secondaryText)
                }
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(.isHeader)

                Spacer(minLength: 0)

                Button {
                    viewModel.dismissSheet()
                } label: {
                    Text("Done")
                        .font(.archivo(.semibold, size: 15, relativeTo: .body))
                        .foregroundStyle(Theme.ink)
                        .padding(.horizontal, 16)
                        .frame(minHeight: 36)
                }
                .buttonStyle(SecondaryCapsuleButtonStyle())
                .accessibilityLabel("Done")
                .accessibilityHint("Closes the results")
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 16)

            Hairline()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(viewModel.results.enumerated()), id: \.element.id) { index, result in
                        if index > 0 {
                            Hairline().padding(.leading, 20)
                        }
                        ResultRow(rank: index + 1, song: result, player: viewModel.player) {
                            viewModel.selectResult(result)
                        } onFindSimilar: {
                            viewModel.selectResult(result)
                            viewModel.findSimilar()
                        }
                        .contextMenu {
                            SongActions(song: result, onFindSimilar: {
                                viewModel.selectResult(result)
                                viewModel.findSimilar()
                            })
                        }
                    }

                    Text(viewModel.isRefining
                         ? "Analyzing more songs like this… the list will update."
                         : "Tap any song to search from it.")
                        .font(.archivo(.regular, size: 12, relativeTo: .caption))
                        .foregroundStyle(Theme.ink.opacity(0.55))
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                        .padding(.bottom, 12)
                }
            }
            .scrollIndicators(.hidden)
        }
    }
}

private struct ResultRow: View {
    let rank: Int
    let song: Song
    let player: PreviewPlayer
    let action: () -> Void
    let onFindSimilar: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            rowButton
            if song.previewURL != nil {
                PreviewButton(song: song, player: player)
                    .padding(.top, 12)
            }
            SongActionsMenu(song: song, onFindSimilar: onFindSimilar)
                .padding(.top, 12)
                .padding(.trailing, 8)
        }
    }

    private var rowButton: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                Text(rank < 10 ? "0\(rank)" : "\(rank)")
                    .font(.archivo(.extraBold, size: 15, relativeTo: .body))
                    .monospacedDigit()
                    .foregroundStyle(Theme.accent700)
                    .frame(minWidth: 22, minHeight: 44, alignment: .leading)

                ArtworkTile(song: song, size: 44)

                VStack(alignment: .leading, spacing: 2) {
                    Text(song.title)
                        .font(.archivo(.semibold, size: 15, relativeTo: .body))
                        .foregroundStyle(Theme.ink)
                    Text(song.artistAndYear)
                        .font(.archivo(.regular, size: 13, relativeTo: .footnote))
                        .foregroundStyle(Theme.secondaryText)
                    if let why = song.why, !why.isEmpty {
                        Text(why)
                            .font(.archivo(.regular, size: 12, relativeTo: .caption))
                            .foregroundStyle(Theme.ink.opacity(0.75))
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 2)
                    }
                }
                .multilineTextAlignment(.leading)

                Spacer(minLength: 0)
            }
            .padding(.leading, 20)
            .padding(.trailing, 4)
            .padding(.vertical, 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(RowButtonStyle())
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Button styles

struct PrimaryCapsuleButtonStyle: ButtonStyle {
    var isLoading: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(configuration.isPressed ? Theme.accentPressed : Theme.accent)
            .overlay(alignment: .bottom) {
                if isLoading {
                    IndeterminateBar()
                        .transition(.opacity)
                }
            }
            .clipShape(Capsule())
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
            .animation(.easeOut(duration: 0.18), value: isLoading)
    }
}

struct SecondaryCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(Capsule().fill(Color.white.opacity(configuration.isPressed ? 0.8 : 0.55)))
            .overlay(Capsule().strokeBorder(Theme.ink.opacity(0.12), lineWidth: 1))
            .contentShape(Capsule())
    }
}

/// Highlights a row while pressed.
struct RowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(Theme.ink.opacity(configuration.isPressed ? 0.05 : 0))
    }
}

/// 3pt loading bar: an accent-700 track with a light segment sweeping left
/// to right every 0.9s.
struct IndeterminateBar: View {
    private let period: TimeInterval = 0.9

    var body: some View {
        TimelineView(.animation) { context in
            let progress = context.date.timeIntervalSinceReferenceDate
                .truncatingRemainder(dividingBy: period) / period
            GeometryReader { proxy in
                let segment = proxy.size.width * 0.35
                ZStack(alignment: .leading) {
                    Rectangle().fill(Theme.accent700)
                    Rectangle()
                        .fill(Theme.background.opacity(0.9))
                        .frame(width: segment)
                        .offset(x: -segment + (proxy.size.width + segment) * progress)
                }
            }
        }
        .frame(height: 3)
        .accessibilityHidden(true)
    }
}

// MARK: - Previews

private struct SheetPreviewBackdrop: View {
    var body: some View {
        ZStack(alignment: .top) {
            Theme.background.ignoresSafeArea()
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 4), spacing: 12) {
                ForEach(Catalog.songs) { song in
                    ArtworkTile(song: song, size: 72)
                }
            }
            .padding(20)
        }
    }
}

#Preview("Sheet – Confirm") {
    ZStack {
        SheetPreviewBackdrop()
        SongSheet(viewModel: .preview(mode: .confirm))
    }
    .environment(SearchViewModel())
    .environment(PlaylistStore(fileURL: nil))
}

#Preview("Sheet – Results") {
    ZStack {
        SheetPreviewBackdrop()
        SongSheet(viewModel: .preview(mode: .results))
    }
    .environment(SearchViewModel())
    .environment(PlaylistStore(fileURL: nil))
}
