// tb_ocr - OCR de capturas de pantalla del emulador usando Vision.
// Uso: tb_ocr <imagen.png>
// En la franja inferior de subtítulos de TalkBack (y >= 0.845), limpia los píxeles
// oscuros/grises del fondo de la app que se transparentan tras la barra para que
// Vision lea exclusivamente el texto blanco emitido por TalkBack.
import Vision
import AppKit
import CoreGraphics

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let srcCG = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("usage: tb_ocr <image>\n", stderr)
    exit(1)
}

let width = srcCG.width
let height = srcCG.height
let bytesPerPixel = 4
let bytesPerRow = width * bytesPerPixel
var rawData = [UInt8](repeating: 0, count: height * bytesPerRow)

let colorSpace = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(
    data: &rawData,
    width: width,
    height: height,
    bitsPerComponent: 8,
    bytesPerRow: bytesPerRow,
    space: colorSpace,
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
) else {
    exit(2)
}

ctx.draw(srcCG, in: CGRect(x: 0, y: 0, width: width, height: height))

// Extraer en una sola pasada desde el PNG: recuadro verde de foco, barra de caption y firma 8x12
// (evita invocar un segundo `adb exec-out screencap` crudo de 16 MB por cada paso).
var focusMinX = Int.max, focusMinY = Int.max, focusMaxX = -1, focusMaxY = -1
var focusHits = 0
for y in stride(from: 0, to: height, by: 2) {
    let row = y * bytesPerRow
    for x in stride(from: 0, to: width, by: 2) {
        let i = row + x * 4
        let r = Int(rawData[i])
        let g = Int(rawData[i + 1])
        let b = Int(rawData[i + 2])
        if g > 150 && g > r + 45 && g > b + 45 {
            focusHits += 1
            if x < focusMinX { focusMinX = x }
            if y < focusMinY { focusMinY = y }
            if x > focusMaxX { focusMaxX = x }
            if y > focusMaxY { focusMaxY = y }
        }
    }
}
let boxStr = (focusHits >= 8) ? "\(focusMinX),\(focusMinY),\(focusMaxX),\(focusMaxY)" : ""

var bandRows = [Int]()
for y in stride(from: Int(Double(height) * 0.75), to: height, by: 4) {
    var dark = 0
    var total = 0
    let row = y * bytesPerRow
    for x in stride(from: Int(Double(width) * 0.02), to: Int(Double(width) * 0.98), by: 8) {
        let i = row + x * 4
        let r = Int(rawData[i])
        let g = Int(rawData[i + 1])
        let b = Int(rawData[i + 2])
        total += 1
        if r < 120 && g < 120 && b < 120 && abs(r - g) < 25 && abs(g - b) < 25 {
            dark += 1
        }
    }
    if total > 0 && Double(dark) / Double(total) > 0.55 {
        bandRows.append(y)
    }
}
let barStr = (bandRows.count >= 6)
    ? String(format: "%.4f,%.4f", Double(bandRows.first!) / Double(height), Double(bandRows.last!) / Double(height))
    : ""

var sigVals = [String]()
let gw = 8, gh = 12
for gy in 0..<gh {
    for gx in 0..<gw {
        let sx = Int((Double(gx) + 0.5) * Double(width) / Double(gw))
        let sy = Int((Double(gy) + 0.5) * Double(height) / Double(gh))
        let i = sy * bytesPerRow + sx * 4
        let avg = (Int(rawData[i]) + Int(rawData[i + 1]) + Int(rawData[i + 2])) / 3
        sigVals.append(String(avg))
    }
}
print("#META\tsize=\(width),\(height)\tbox=\(boxStr)\tbar=\(barStr)\tsig=\(sigVals.joined(separator: ","))")

// En la franja de la barra de TalkBack (y: 0.845 .. 0.960), el texto real de TalkBack
// es blanco brillante (R,G,B >= 175). El texto de la app que se transparenta detrás
// es oscuro/gris. Aplanamos todo píxel no blanco en esa banda a gris oscuro uniforme.
let yStart = Int(Double(height) * 0.845)
let yEnd = Int(Double(height) * 0.936)
let xStart = Int(Double(width) * 0.03)
let xEnd = Int(Double(width) * 0.97)

for y in yStart..<yEnd {
    let rowOffset = y * bytesPerRow
    for x in xStart..<xEnd {
        let idx = rowOffset + x * 4
        let r = rawData[idx]
        let g = rawData[idx + 1]
        let b = rawData[idx + 2]
        if r < 170 || g < 170 || b < 170 {
            rawData[idx] = 58
            rawData[idx + 1] = 58
            rawData[idx + 2] = 58
        }
    }
}

let cleanCG = ctx.makeImage() ?? srcCG

let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = ["es-ES", "en-US"]
req.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cleanCG)
do {
    try handler.perform([req])
} catch {
    fputs("OCR error: \(error)\n", stderr)
    exit(2)
}

for obs in req.results ?? [] {
    if let s = obs.topCandidates(1).first {
        let b = obs.boundingBox // origen bottom-left en Vision -> convertir a top-left
        print(String(format: "%.4f,%.4f,%.4f,%.4f\t%@",
                     b.origin.x, 1.0 - b.origin.y - b.size.height,
                     b.size.width, b.size.height, s.string))
    }
}
