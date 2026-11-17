// tb_video - Generador nativo de clips H.264 (.mp4) cortos para evidencias Jira y comparativas Before/After.
// Uso: tb_video <spec.json>
// Compila con AVFoundation + AppKit + CoreGraphics sin requerir ffmpeg ni librerias externas.
import Foundation
import AVFoundation
import AppKit
import CoreGraphics

struct SlideItem: Decodable {
    let png: String
    let label: String
    let sublabel: String?
    let badge: String?
    let isFlagged: Bool?
    let durationSec: Double?
}

struct SidePair: Decodable {
    let leftPng: String
    let leftLabel: String
    let rightPng: String
    let rightLabel: String
    let durationSec: Double?
}

struct VideoSpec: Decodable {
    let mode: String? // "slides" | "side_by_side"
    let output: String
    let title: String?
    let leftHeader: String?
    let rightHeader: String?
    let maxHeight: Int?
    let fps: Int?
    let slides: [SlideItem]?
    let pairs: [SidePair]?
}

guard CommandLine.arguments.count > 1 else {
    fputs("usage: tb_video <spec.json>\n", stderr)
    exit(1)
}

let specPath = CommandLine.arguments[1]
guard let specData = try? Data(contentsOf: URL(fileURLWithPath: specPath)),
      let spec = try? JSONDecoder().decode(VideoSpec.self, from: specData) else {
    fputs("tb_video: invalid JSON spec\n", stderr)
    exit(2)
}

func loadCG(_ path: String) -> CGImage? {
    guard let ns = NSImage(contentsOfFile: path) else { return nil }
    return ns.cgImage(forProposedRect: nil, context: nil, hints: nil)
}

func evenInt(_ v: Int) -> Int {
    let clamped = max(16, v)
    return (clamped % 2 == 0) ? clamped : (clamped + 1)
}

func drawText(_ text: String, rect: CGRect, font: NSFont, color: NSColor, align: NSTextAlignment = .left) {
    let style = NSMutableParagraphStyle()
    style.alignment = align
    style.lineBreakMode = .byTruncatingTail
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: color,
        .paragraphStyle: style
    ]
    (text as NSString).draw(in: rect, withAttributes: attrs)
}

func makePixelBuffer(width: Int, height: Int, drawBlock: (CGContext) -> Void) -> CVPixelBuffer? {
    var pbOut: CVPixelBuffer? = nil
    let attrs: [CFString: Any] = [
        kCVPixelBufferCGImageCompatibilityKey: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey: true
    ]
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32ARGB,
        attrs as CFDictionary,
        &pbOut
    )
    guard status == kCVReturnSuccess, let pb = pbOut else { return nil }
    CVPixelBufferLockBaseAddress(pb, [])
    defer { CVPixelBufferUnlockBaseAddress(pb, []) }
    guard let base = CVPixelBufferGetBaseAddress(pb) else { return nil }
    let bytesPerRow = CVPixelBufferGetBytesPerRow(pb)
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(
        data: base,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: cs,
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue
    ) else { return nil }

    NSGraphicsContext.saveGraphicsState()
    let nsCtx = NSGraphicsContext(cgContext: ctx, flipped: false)
    NSGraphicsContext.current = nsCtx
    drawBlock(ctx)
    NSGraphicsContext.restoreGraphicsState()
    return pb
}

let mode = spec.mode ?? "slides"
let fps = Int32(max(4, min(30, spec.fps ?? 10)))
let maxH = spec.maxHeight ?? 1180
let outURL = URL(fileURLWithPath: spec.output)
try? FileManager.default.removeItem(at: outURL)
try? FileManager.default.createDirectory(at: outURL.deletingLastPathComponent(), withIntermediateDirectories: true)

var canvasW = 640
var canvasH = 1180
let hudH: CGFloat = 94

if mode == "side_by_side", let firstPair = spec.pairs?.first,
   let imgL = loadCG(firstPair.leftPng) ?? loadCG(firstPair.rightPng) {
    let scale = min(1.0, Double(maxH - Int(hudH)) / Double(max(1, imgL.height)))
    let singleW = Int(Double(imgL.width) * scale)
    let singleH = Int(Double(imgL.height) * scale)
    canvasW = evenInt(singleW * 2 + 24)
    canvasH = evenInt(singleH + Int(hudH) + 12)
} else if let firstSlide = spec.slides?.first, let img = loadCG(firstSlide.png) {
    let scale = min(1.0, Double(maxH - Int(hudH)) / Double(max(1, img.height)))
    canvasW = evenInt(max(460, Int(Double(img.width) * scale)))
    canvasH = evenInt(Int(Double(img.height) * scale) + Int(hudH))
}

guard let writer = try? AVAssetWriter(outputURL: outURL, fileType: .mp4) else {
    fputs("tb_video: failed to init AVAssetWriter\n", stderr)
    exit(3)
}

let videoSettings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: canvasW,
    AVVideoHeightKey: canvasH,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: mode == "side_by_side" ? 1_800_000 : 1_100_000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264MainAutoLevel
    ]
]

let writerInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
writerInput.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: writerInput,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: Int(kCVPixelFormatType_32ARGB),
        kCVPixelBufferWidthKey as String: canvasW,
        kCVPixelBufferHeightKey as String: canvasH
    ]
)

guard writer.canAdd(writerInput) else { exit(4) }
writer.add(writerInput)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

var frameTick: Int64 = 0

func appendBuffer(_ pb: CVPixelBuffer, frames count: Int) {
    for _ in 0..<max(1, count) {
        while !writerInput.isReadyForMoreMediaData {
            Thread.sleep(forTimeInterval: 0.005)
        }
        let pts = CMTime(value: frameTick, timescale: fps)
        adaptor.append(pb, withPresentationTime: pts)
        frameTick += 1
    }
}

if mode == "side_by_side", let pairs = spec.pairs, !pairs.isEmpty {
    let total = pairs.count
    for (idx, pair) in pairs.enumerated() {
        let cgL = loadCG(pair.leftPng)
        let cgR = loadCG(pair.rightPng)
        let dur = pair.durationSec ?? 1.6
        let nFrames = max(2, Int((dur * Double(fps)).rounded()))
        let progress = CGFloat(idx + 1) / CGFloat(max(1, total))

        if let pb = makePixelBuffer(width: canvasW, height: canvasH, drawBlock: { ctx in
            ctx.setFillColor(NSColor(calibratedRed: 0.06, green: 0.09, blue: 0.16, alpha: 1.0).cgColor)
            ctx.fill(CGRect(x: 0, y: 0, width: canvasW, height: canvasH))

            let bodyH = CGFloat(canvasH) - hudH - 8
            let slotW = (CGFloat(canvasW) - 24) / 2.0
            if let l = cgL {
                ctx.draw(l, in: CGRect(x: 8, y: 8, width: slotW, height: bodyH))
            }
            if let r = cgR {
                ctx.draw(r, in: CGRect(x: 16 + slotW, y: 8, width: slotW, height: bodyH))
            }

            let hudY = CGFloat(canvasH) - hudH
            ctx.setFillColor(NSColor(calibratedRed: 0.06, green: 0.09, blue: 0.16, alpha: 1.0).cgColor)
            ctx.fill(CGRect(x: 0, y: hudY, width: CGFloat(canvasW), height: hudH))

            ctx.setFillColor(NSColor(calibratedRed: 0.01, green: 0.52, blue: 0.78, alpha: 1.0).cgColor)
            ctx.fill(CGRect(x: 0, y: hudY, width: CGFloat(canvasW) * progress, height: 3))

            let titleStr = spec.title ?? "Comparativa TalkBack"
            drawText(
                "\(titleStr)  (\(idx + 1)/\(total))",
                rect: CGRect(x: 12, y: hudY + 62, width: CGFloat(canvasW) - 24, height: 22),
                font: NSFont.boldSystemFont(ofSize: 14),
                color: NSColor(calibratedRed: 0.49, green: 0.83, blue: 0.99, alpha: 1.0)
            )
            let lHdr = spec.leftHeader ?? "ANTES"
            let rHdr = spec.rightHeader ?? "DESPUES"
            drawText(
                "\(lHdr): \(pair.leftLabel)",
                rect: CGRect(x: 12, y: hudY + 10, width: slotW - 8, height: 46),
                font: NSFont.systemFont(ofSize: 12.5, weight: .medium),
                color: NSColor(calibratedRed: 0.99, green: 0.75, blue: 0.75, alpha: 1.0)
            )
            drawText(
                "\(rHdr): \(pair.rightLabel)",
                rect: CGRect(x: 16 + slotW, y: hudY + 10, width: slotW - 8, height: 46),
                font: NSFont.systemFont(ofSize: 12.5, weight: .medium),
                color: NSColor(calibratedRed: 0.73, green: 0.97, blue: 0.82, alpha: 1.0)
            )
        }) {
            appendBuffer(pb, frames: nFrames)
        }
    }
} else if let slides = spec.slides, !slides.isEmpty {
    let total = slides.count
    for (idx, item) in slides.enumerated() {
        guard let cg = loadCG(item.png) else { continue }
        let dur = item.durationSec ?? 1.45
        let nFrames = max(2, Int((dur * Double(fps)).rounded()))
        let progress = CGFloat(idx + 1) / CGFloat(max(1, total))
        let flagged = item.isFlagged ?? false

        if let pb = makePixelBuffer(width: canvasW, height: canvasH, drawBlock: { ctx in
            ctx.setFillColor(NSColor(calibratedRed: 0.06, green: 0.09, blue: 0.16, alpha: 1.0).cgColor)
            ctx.fill(CGRect(x: 0, y: 0, width: canvasW, height: canvasH))

            let imgH = CGFloat(canvasH) - hudH
            ctx.draw(cg, in: CGRect(x: 0, y: 0, width: CGFloat(canvasW), height: imgH))

            let hudY = imgH
            let bgColor = flagged
                ? NSColor(calibratedRed: 0.22, green: 0.07, blue: 0.09, alpha: 1.0)
                : NSColor(calibratedRed: 0.06, green: 0.09, blue: 0.16, alpha: 1.0)
            ctx.setFillColor(bgColor.cgColor)
            ctx.fill(CGRect(x: 0, y: hudY, width: CGFloat(canvasW), height: hudH))

            let barColor = flagged
                ? NSColor(calibratedRed: 0.94, green: 0.27, blue: 0.27, alpha: 1.0)
                : NSColor(calibratedRed: 0.01, green: 0.52, blue: 0.78, alpha: 1.0)
            ctx.setFillColor(barColor.cgColor)
            ctx.fill(CGRect(x: 0, y: hudY, width: CGFloat(canvasW) * progress, height: 4))

            let badgeTxt = item.badge ?? "PASO \(idx + 1)/\(total)"
            let topLine = (spec.title != nil) ? "\(badgeTxt)  ·  \(spec.title!)" : badgeTxt
            drawText(
                topLine,
                rect: CGRect(x: 14, y: hudY + 62, width: CGFloat(canvasW) - 28, height: 22),
                font: NSFont.boldSystemFont(ofSize: 13.5),
                color: flagged
                    ? NSColor(calibratedRed: 0.99, green: 0.65, blue: 0.65, alpha: 1.0)
                    : NSColor(calibratedRed: 0.49, green: 0.83, blue: 0.99, alpha: 1.0)
            )
            drawText(
                item.label,
                rect: CGRect(x: 14, y: hudY + 12, width: CGFloat(canvasW) - 28, height: 46),
                font: NSFont.systemFont(ofSize: 14, weight: .semibold),
                color: NSColor.white
            )
        }) {
            appendBuffer(pb, frames: nFrames)
        }
    }
}

writerInput.markAsFinished()
let sema = DispatchSemaphore(value: 0)
writer.finishWriting {
    sema.signal()
}
sema.wait()

if writer.status != .completed {
    fputs("tb_video: encoding failed (\(writer.error?.localizedDescription ?? "unknown"))\n", stderr)
    exit(5)
}
print(spec.output)
