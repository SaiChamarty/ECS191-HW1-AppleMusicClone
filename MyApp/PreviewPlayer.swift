import AVFoundation
import Observation
import SwiftUI

/// Round play/stop button for a song's 30-second preview, used in every song list.
struct PreviewButton: View {
    let song: Song
    let player: PreviewPlayer

    var body: some View {
        let isPlaying = player.isPlaying(song)
        Button {
            player.toggle(song)
        } label: {
            Image(systemName: isPlaying ? "stop.fill" : "play.fill")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(isPlaying ? Theme.background : Theme.ink)
                .frame(width: 30, height: 30)
                .background(Circle().fill(isPlaying ? Theme.accent : Color.white.opacity(0.55)))
                .overlay(Circle().strokeBorder(Theme.ink.opacity(isPlaying ? 0 : 0.12), lineWidth: 1))
                .frame(width: 38, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isPlaying ? "Stop preview" : "Play preview")
        .accessibilityValue("\(song.title), \(song.artist)")
    }
}

/// Plays 30-second song previews, one at a time.
@Observable
final class PreviewPlayer {
    private(set) var playingSongID: Song.ID?

    @ObservationIgnored private var player: AVPlayer?
    @ObservationIgnored private var endObserver: NSObjectProtocol?

    func isPlaying(_ song: Song) -> Bool {
        playingSongID == song.id
    }

    /// Starts `song`'s preview, or stops it if it's already playing.
    func toggle(_ song: Song) {
        if isPlaying(song) {
            stop()
            return
        }
        guard let url = song.previewURL else { return }
        stop()
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
        let item = AVPlayerItem(url: url)
        let player = AVPlayer(playerItem: item)
        endObserver = NotificationCenter.default.addObserver(
            forName: AVPlayerItem.didPlayToEndTimeNotification, object: item, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.stop() }
        }
        self.player = player
        playingSongID = song.id
        player.play()
    }

    func stop() {
        player?.pause()
        player = nil
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
        }
        endObserver = nil
        playingSongID = nil
    }
}
