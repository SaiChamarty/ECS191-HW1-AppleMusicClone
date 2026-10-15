import Foundation

struct Song: Identifiable, Hashable, Codable {
    let id: String
    let title: String
    let artist: String
    /// Release year; 0 when unknown.
    let year: Int
    let tags: [String]
    /// Short explanation of why this song is similar (only set on similarity results).
    var why: String?

    // Catalog details, set for songs that come from the similarity service.
    var trackID: Int?
    var album: String?
    var genre: String?
    /// 30-second preview clip.
    var previewURL: URL?
    var artworkURL: URL?

    init(
        title: String,
        artist: String,
        year: Int,
        tags: [String] = [],
        why: String? = nil,
        trackID: Int? = nil,
        album: String? = nil,
        genre: String? = nil,
        previewURL: URL? = nil,
        artworkURL: URL? = nil
    ) {
        self.id = "\(title)|\(artist)".lowercased()
        self.title = title
        self.artist = artist
        self.year = year
        self.tags = tags
        self.why = why
        self.trackID = trackID
        self.album = album
        self.genre = genre
        self.previewURL = previewURL
        self.artworkURL = artworkURL
    }

    /// "Artist · Year", or just the artist when the year is unknown.
    var artistAndYear: String {
        year > 0 ? "\(artist) · \(year)" : artist
    }
}
