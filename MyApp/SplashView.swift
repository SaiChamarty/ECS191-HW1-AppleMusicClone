import SwiftUI

/// Launch splash: "SoundAlike" centered on white, set in San Francisco (the
/// typeface of the Apple Music wordmark) with Apple Music's red gradient.
struct SplashView: View {
    /// Apple Music brand reds, light (top) to deep (bottom).
    static let musicRedLight = Color(hex: 0xFB5C74)
    static let musicRed = Color(hex: 0xFA233B)

    var body: some View {
        ZStack {
            Color.white
                .ignoresSafeArea()

            Text("SoundAlike")
                .font(.system(size: 44, weight: .bold, design: .default))
                .tracking(-0.5)
                .foregroundStyle(
                    LinearGradient(
                        colors: [Self.musicRedLight, Self.musicRed],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .accessibilityAddTraits(.isHeader)
        }
    }
}

#Preview {
    SplashView()
}
