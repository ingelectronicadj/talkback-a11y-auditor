# tb_ocr.ps1 - OCR de capturas del emulador usando Windows.Media.Ocr (WinRT).
# Equivalente Windows de tb_ocr (macOS/Vision). Requiere PowerShell 5.1+ (powershell.exe)
# o PowerShell 7 en Windows. Sin dependencias externas.
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File tb_ocr.ps1 <imagen.png>
# Salida por linea: "x,y,w,h<TAB>texto" con coordenadas normalizadas (0..1, origen top-left).
param(
  [Parameter(Mandatory=$true, Position=0)]
  [string]$ImagePath
)

$ErrorActionPreference = 'Stop'
# El texto de TalkBack en espanol incluye acentos / n / signos de apertura;
# forzamos UTF-8 para que Python lo decodifique igual que la salida de macOS.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
Add-Type -AssemblyName System.Drawing
try { Add-Type -AssemblyName System.Runtime.WindowsRuntime } catch {}

# En la franja de la barra de TalkBack (y: 0.845..0.936, x: 0.03..0.97), el texto real
# es blanco brillante; el texto de la app que se transparenta detras es oscuro/gris.
# Aplanamos todo pixel no blanco de esa banda a gris oscuro uniforme (mismo criterio
# que tb_ocr.swift: canal < 170 -> 58).
$prep = @'
using System;
using System.Drawing;
using System.Drawing.Imaging;

public static class ImgPrep {
  public static void FlattenCaptionBand(string src, string dst) {
    // Normalizamos a 32bppArgb: LockBits en modo ReadWrite exige el formato nativo
    // del bitmap y los PNG del emulador pueden venir en 24bpp.
    using (Bitmap srcBmp = new Bitmap(src))
    using (Bitmap bmp = new Bitmap(srcBmp.Width, srcBmp.Height, PixelFormat.Format32bppArgb)) {
      using (Graphics g = Graphics.FromImage(bmp)) {
        g.DrawImageUnscaled(srcBmp, 0, 0);
      }
      int w = bmp.Width, h = bmp.Height;
      Rectangle rect = new Rectangle(0, 0, w, h);
      BitmapData data = bmp.LockBits(rect, ImageLockMode.ReadWrite, PixelFormat.Format32bppArgb);
      int bytes = Math.Abs(data.Stride) * h;
      byte[] px = new byte[bytes];
      System.Runtime.InteropServices.Marshal.Copy(data.Scan0, px, 0, bytes);
      int yStart = (int)(h * 0.845), yEnd = (int)(h * 0.936);
      int xStart = (int)(w * 0.03), xEnd = (int)(w * 0.97);
      for (int y = yStart; y < yEnd; y++) {
        int row = y * data.Stride;
        for (int x = xStart; x < xEnd; x++) {
          int i = row + x * 4;
          if (px[i] < 170 || px[i + 1] < 170 || px[i + 2] < 170) {
            px[i] = 58; px[i + 1] = 58; px[i + 2] = 58; px[i + 3] = 255;
          }
        }
      }
      System.Runtime.InteropServices.Marshal.Copy(px, 0, data.Scan0, bytes);
      bmp.UnlockBits(data);
      bmp.Save(dst, ImageFormat.Png);
    }
  }
}
'@
Add-Type -TypeDefinition $prep -ReferencedAssemblies System.Drawing

# Ayudante para esperar IAsyncOperation WinRT desde PowerShell
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-Operation($AsyncOp, $ResultType) {
  $task = $asTaskGeneric.MakeGenericMethod($ResultType).Invoke($null, @($AsyncOp))
  $task.Wait()
  return $task.Result
}

$resolved = (Resolve-Path $ImagePath).Path
$tmp = Join-Path $env:TEMP ("tb_ocr_flat_" + [guid]::NewGuid().ToString("N") + ".png")
try {
  [ImgPrep]::FlattenCaptionBand($resolved, $tmp)

  $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
  $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
  $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]

  $file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($tmp)) ([Windows.Storage.StorageFile])
  $stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $sbmp = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  $stream.Dispose()

  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if ($null -eq $engine) {
    # Probar language packs comunes instalados (es-ES, es-MX, es-419, en-US).
    # ::new() funciona en PS5.1 y PS7; New-Object solo activa WinRT en PS5.1.
    foreach ($tag in @("es-ES", "es-MX", "es-419", "es-AR", "en-US")) {
      $lang = $null
      try {
        $lang = [Windows.Globalization.Language]::new($tag)
      } catch {
        try { $lang = New-Object Windows.Globalization.Language -ArgumentList $tag } catch {}
      }
      if ($null -ne $lang) {
        try { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang) } catch {}
        if ($null -ne $engine) { break }
      }
    }
  }
  if ($null -eq $engine) { exit 2 }

  $result = Await-Operation ($engine.RecognizeAsync($sbmp)) ([Windows.Media.Ocr.OcrResult])

  $srcBmp = New-Object System.Drawing.Bitmap $resolved
  $w = $srcBmp.Width; $h = $srcBmp.Height
  $srcBmp.Dispose()
  $inv = [System.Globalization.CultureInfo]::InvariantCulture

  foreach ($line in $result.Lines) {
    $x1 = [double]::MaxValue; $y1 = [double]::MaxValue; $x2 = 0.0; $y2 = 0.0
    foreach ($word in $line.Words) {
      $r = $word.BoundingRect
      if ($r.X -lt $x1) { $x1 = $r.X }
      if ($r.Y -lt $y1) { $y1 = $r.Y }
      if (($r.X + $r.Width) -gt $x2) { $x2 = $r.X + $r.Width }
      if (($r.Y + $r.Height) -gt $y2) { $y2 = $r.Y + $r.Height }
    }
    if ($x2 -le $x1 -or $y2 -le $y1) { continue }
    $text = ($line.Words | ForEach-Object { $_.Text }) -join ' '
    [Console]::Out.Write((
      [string]::Format($inv, "{0:F4},{1:F4},{2:F4},{3:F4}`t{4}",
        ($x1 / $w), ($y1 / $h), (($x2 - $x1) / $w), (($y2 - $y1) / $h), $text)) + "`n")
  }
} finally {
  if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}
