import SwiftUI

/// Album art: a colored square with the title's first letter, covered by the
/// real artwork when the song has an artwork URL (catalog search results).
struct ArtworkTile: View {
    let title: String
    let artist: String
    let size: CGFloat
    var artworkURL: URL?

    init(title: String, artist: String, size: CGFloat, artworkURL: URL? = nil) {
        self.title = title
        self.artist = artist
        self.size = size
        self.artworkURL = artworkURL
    }

    init(song: Song, size: CGFloat) {
        self.title = song.title
        self.artist = song.artist
        self.size = size
        self.artworkURL = song.artworkURL
    }

    private static let palette: [(background: Color, foreground: Color)] = [
        (Theme.ink, Theme.background),
        (Theme.accent, Theme.background),
        (Theme.surface, Theme.ink),
        (Color(hex: 0xFAD9D2), Color(hex: 0x4A120A)),
        (.white, Theme.accent),
    ]

    /// Stable string hash (h = h * 31 + char, unsigned 32-bit) so a song
    /// always gets the same color.
    private var colors: (background: Color, foreground: Color) {
        var hash: UInt32 = 0
        for unit in (title + artist).utf16 {
            hash = hash &* 31 &+ UInt32(unit)
        }
        return Self.palette[Int(hash % UInt32(Self.palette.count))]
    }

    private var initial: String {
        guard let first = title.first(where: { $0.isLetter || $0.isNumber }) else { return "#" }
        return String(first).uppercased()
    }

    private var cornerRadius: CGFloat {
        size >= 80 ? 10 : 6
    }

    var body: some View {
        let colors = colors
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(colors.background)
            .overlay(alignment: .bottomLeading) {
                Text(initial)
                    .font(.archivo(.extraBold, fixedSize: size * 0.42))
                    .foregroundStyle(colors.foreground)
                    .padding(.leading, 5)
                    .padding(.bottom, 3)
            }
            .overlay {
                // The placeholder stays visible while loading or if loading fails.
                if let artworkURL {
                    AsyncImage(url: artworkURL) { image in
                        image.resizable().scaledToFill()
                    } placeholder: {
                        Color.clear
                    }
                    .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
                }
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
    }
}

#Preview("Artwork tiles") {
    VStack(alignment: .leading, spacing: 20) {
        HStack(spacing: 12) {
            ForEach(Catalog.songs.prefix(5)) { song in
                ArtworkTile(song: song, size: 48)
            }
        }
        HStack(spacing: 12) {
            ForEach(Catalog.songs.dropFirst(5).prefix(6)) { song in
                ArtworkTile(song: song, size: 44)
            }
        }
        HStack(spacing: 12) {
            ForEach(Catalog.songs.suffix(3)) { song in
                ArtworkTile(song: song, size: 92)
            }
        }
    }
    .padding(20)
    .background(Theme.background)
}
