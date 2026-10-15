import SwiftUI

/// Design tokens for Sound-alike.
enum Theme {
    static let background = Color(hex: 0xF3F2F2)
    static let ink = Color(hex: 0x201E1D)
    static let surface = Color(hex: 0xEAE9E9)
    static let accent = Color(hex: 0xEC3013)
    /// accent-700: used for small red text.
    static let accent700 = Color(hex: 0xA3200C)
    /// accent-300: light ring around the focused search field.
    static let accent300 = Color(hex: 0xF7B3A6)
    static let accentPressed = Color(hex: 0xC42810)
    static let sheetTint = Color(hex: 0xFAF8F8)

    static let secondaryText = ink.opacity(0.6)
    static let hairline = ink.opacity(0.13)
}

extension Color {
    /// Creates an opaque sRGB color from a 0xRRGGBB literal.
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

// MARK: - Typography

/// PostScript names of the bundled Archivo faces (registered via UIAppFonts).
enum ArchivoWeight: String {
    case regular = "Archivo-Regular"     // 400
    case medium = "Archivo-Medium"       // 500
    case semibold = "Archivo-SemiBold"   // 600
    case extraBold = "Archivo-ExtraBold" // 800
}

extension Font {
    /// Archivo at a design size that scales with Dynamic Type relative to `textStyle`.
    static func archivo(_ weight: ArchivoWeight, size: CGFloat, relativeTo textStyle: Font.TextStyle = .body) -> Font {
        .custom(weight.rawValue, size: size, relativeTo: textStyle)
    }

    /// Archivo at a fixed size (for artwork lettering that must match its tile).
    static func archivo(_ weight: ArchivoWeight, fixedSize size: CGFloat) -> Font {
        .custom(weight.rawValue, fixedSize: size)
    }
}

// MARK: - Shared components

/// Small uppercase label: 11pt, semibold, 0.12em tracking, deep accent.
struct Kicker: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text.uppercased())
            .font(.archivo(.semibold, size: 11, relativeTo: .caption2))
            .tracking(11 * 0.12)
            .foregroundStyle(Theme.accent700)
    }
}

/// 1pt divider in ink at ~13% opacity.
struct Hairline: View {
    var body: some View {
        Rectangle()
            .fill(Theme.hairline)
            .frame(height: 1)
    }
}
