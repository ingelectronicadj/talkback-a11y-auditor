"""Procesamiento visual del framebuffer (recuadro verde, barra de caption, firma) y OCR Vision."""

import os
import re
import subprocess
from .config import SCRIPT_DIR
from .rules import norm_utt


def find_focus_box(w, h, px):
    """Localiza el rectángulo verde del foco de TalkBack -> (x1,y1,x2,y2) o None."""
    xs, ys = [], []
    stride = w * 4
    for y in range(0, h, 2):
        row = y * stride
        for x in range(0, w, 2):
            i = row + x * 4
            r, g, b = px[i], px[i + 1], px[i + 2]
            if g > 150 and g > r + 45 and g > b + 45:
                xs.append(x)
                ys.append(y)
    if len(xs) < 8:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _is_fullscreen_container(n):
    short = (n.get("cls") or "").split(".")[-1]
    if short in ("WebView", "ComposeView", "ViewFactoryHolder", "FrameLayout", "LinearLayout"):
        return True
    b = n.get("bounds")
    if b and (b[2] - b[0]) * (b[3] - b[1]) > 1800000:
        return True
    return False


def match_node(box, nodes, utterance=""):
    """Correlaciona el paso con su nodo accesible en `nodes`:
    1) Si hay `utterance`, prioriza el nodo cuyo texto/content-desc coincide con el anuncio
       (robusto frente al scroll del WebView tras el dump inicial).
    2) Si varios nodos tienen el mismo texto o no hay match textual, usa la geometría `box`."""
    utt_n = norm_utt(utterance)
    if utt_n and len(utt_n) >= 2:
        candidates = []
        for n in nodes:
            if _is_fullscreen_container(n):
                continue
            lbl = (n.get("desc") or n.get("text") or "").strip()
            ln = norm_utt(lbl)
            if not ln:
                continue
            if ln == utt_n or (len(ln) >= 3 and ln in utt_n) or (len(utt_n) >= 4 and utt_n in ln):
                # Preferir coincidencia más específica; desempatar por proximidad geométrica a box
                dist = 999999
                if box and n.get("bounds"):
                    bx, by = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
                    nx, ny = (n["bounds"][0] + n["bounds"][2]) // 2, (n["bounds"][1] + n["bounds"][3]) // 2
                    dist = abs(bx - nx) + abs(by - ny)
                candidates.append((min(len(ln), len(utt_n)), -dist, n))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            return candidates[0][2]

    best_cover, best_center = None, None
    if box:
        bx1, by1, bx2, by2 = box
        barea = max(1, (bx2 - bx1) * (by2 - by1))
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2
        for n in nodes:
            if not n.get("bounds") or _is_fullscreen_container(n):
                continue
            x1, y1, x2, y2 = n["bounds"]
            area = (x2 - x1) * (y2 - y1)
            if area <= 0 or area > 1800000:
                continue
            iw = max(0, min(bx2, x2) - max(bx1, x1))
            ih = max(0, min(by2, y2) - max(by1, y1))
            inter = iw * ih
            if inter / barea > 0.55 and (best_cover is None or area < best_cover[0]):
                best_cover = (area, n)
            if x1 <= cx <= x2 and y1 <= cy <= y2 and (best_center is None or area < best_center[0]):
                best_center = (area, n)
    return (best_cover or best_center or (None, None))[1]


def effective_label(node, nodes):
    """Etiqueta del nodo enfocado; si el foco está en un contenedor pequeño sin texto,
    agrega los textos de los nodos contenidos en sus bounds."""
    if not node or _is_fullscreen_container(node):
        return ""
    label = (node.get("desc") or node.get("text") or "").strip()
    if label:
        return label
    if not node.get("bounds"):
        return ""
    x1, y1, x2, y2 = node["bounds"]
    if (x2 - x1) * (y2 - y1) > 900000:
        return ""
    inner = []
    for n in nodes:
        if not n.get("bounds") or n is node:
            continue
        nx1, ny1, nx2, ny2 = n["bounds"]
        if x1 <= nx1 and ny1 >= y1 and nx2 <= x2 and ny2 <= y2:
            t = (n.get("desc") or n.get("text") or "").strip()
            if t:
                inner.append((ny1, nx1, t))
    inner.sort()
    return " ".join(t for _, _, t in inner)[:180]


def find_caption_bar(w, h, px):
    """Rango-y (0..1) de la barra oscura de speech output de TalkBack."""
    stride = w * 4
    band_rows = []
    for y in range(int(h * 0.75), h, 4):
        dark = 0
        total = 0
        for x in range(int(w * 0.02), int(w * 0.98), 8):
            i = y * stride + x * 4
            r, g, b = px[i], px[i + 1], px[i + 2]
            total += 1
            if r < 120 and g < 120 and b < 120 and abs(r - g) < 25 and abs(g - b) < 25:
                dark += 1
        if total and dark / total > 0.55:
            band_rows.append(y)
    if len(band_rows) < 6:
        return None
    return min(band_rows) / h, max(band_rows) / h


def screen_sig(w, h, px):
    """Firma visual grosera de la pantalla (grid 8x12, canal medio)."""
    sig, gw, gh = [], 8, 12
    stride = w * 4
    for gy in range(gh):
        for gx in range(gw):
            x = int((gx + 0.5) * w / gw)
            y = int((gy + 0.5) * h / gh)
            i = y * stride + x * 4
            sig.append((px[i] + px[i + 1] + px[i + 2]) // 3)
    return tuple(sig)


def sig_diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) if a and b else 0


def ensure_ocr_binary():
    src = os.path.join(SCRIPT_DIR, "tb_ocr.swift")
    binpath = os.path.join(SCRIPT_DIR, "tb_ocr")
    if os.path.exists(binpath):
        return binpath
    try:
        subprocess.run(
            ["swiftc", "-O", src, "-o", binpath],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return binpath
    except Exception as e:
        print("OCR no disponible (%s); el reporte usará solo el texto del nodo." % e)
        return None


def ocr_step_info(ocr_bin, png_path, bar_y=None):
    """Analiza por OCR la captura completa del paso y devuelve:
      - utterance: texto limpio anunciado en la barra de TalkBack
      - raw_caption: texto crudo de la barra (incluyendo 'TalkBack menu. Button')
      - page_title: título visible de la vista o drawer en la franja superior
      - is_skeleton: True si hay título de vista/drawer pero el cuerpo central
        (0.185 < cy < bar_y) carece por completo de texto (skeletons grises).
    """
    if not ocr_bin:
        return {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False}
    try:
        out = subprocess.run(
            [ocr_bin, png_path], capture_output=True, text=True, timeout=60
        ).stdout
    except Exception:
        return {"utterance": "", "raw_caption": "", "page_title": "", "is_skeleton": False}
    y_lo, y_hi = bar_y if bar_y else (0.82, 0.97)
    parsed = []
    tb_hdr_y = None
    for ln in out.splitlines():
        m = re.match(r"([\d.]+),([\d.]+),([\d.]+),([\d.]+)\t(.*)", ln)
        if not m:
            continue
        x, y, w, h, txt = (
            float(m[1]),
            float(m[2]),
            float(m[3]),
            float(m[4]),
            m[5].strip(),
        )
        cy = y + h / 2
        parsed.append((x, y, w, h, cy, txt))
        if 0.82 <= cy <= 0.90 and x <= 0.14 and txt.lower().startswith("talkback"):
            tb_hdr_y = cy

    # El texto hablado real en la barra de TalkBack siempre aparece alineado a la
    # izquierda (x <= 0.14) y debajo del encabezado "TalkBack" (tb_hdr_y + 0.012 .. + 0.076).
    # Filtrar por x <= 0.14 evita mezclar textos de la app centrados o a la derecha
    # ("Siguiente", "$ 11.302.349,02", "Acciones", "Aprende") que se transparentan detrás.
    cap_y_min = (tb_hdr_y + 0.012) if tb_hdr_y else max(y_lo, 0.880)
    cap_y_max = (tb_hdr_y + 0.066) if tb_hdr_y else min(y_hi, 0.934)
    cap_lines, hdr_lines, body_lines = [], [], []
    for x, y, w, h, cy, txt in parsed:
        if cap_y_min <= cy <= cap_y_max and x <= 0.75:
            cap_lines.append((cy, txt))
        elif 0.05 <= cy <= 0.185:
            if len(txt.strip(" <×xX•·")) >= 3:
                hdr_lines.append((cy, x, txt))
        elif 0.185 < cy < 0.83:
            if len(txt.strip(" •·.,:")) >= 2:
                body_lines.append((cy, txt))
    cap_lines.sort()
    hdr_lines.sort()
    raw_parts = [
        t.strip()
        for _, t in cap_lines
        if t.strip() and t.strip().lower() not in ("talkback", "x", "⋮", "••c", "•oc")
    ]
    raw_caption = " · ".join(raw_parts)
    noise = {
        "talkback", "x", "⋮", "speech output", "ot", "talkback ot",
        "talkback on", "se activó talkback", "se activo talkback",
        "menú de talkback", "menu", "menu. button", "on", "4", "5", "6", "7", "8", "9", "0",
    }
    clean = []
    for _, t in cap_lines:
        raw_l = t.lower().strip(" ·.,:")
        if (
            not raw_l
            or raw_l in noise
            or raw_l.startswith("talkback menu")
            or raw_l.startswith("menú de talkback")
            or raw_l.startswith("talkback on")
            or raw_l.startswith("se activó talkback")
        ):
            continue
        t = re.sub(
            r"\b(TalkBack\s*(menu\.?\s*(Button)?|on|OT)?|Menú de TalkBack\.?\s*(Botón)?|Se activó TalkBack)\b",
            "",
            t,
            flags=re.I,
        ).strip(" ·.,:")
        tl = t.lower().strip(" ·.,:")
        if not t or tl in noise or tl.startswith("talkback menu"):
            continue
        clean.append(t)
    dedup = []
    for t in clean:
        if not dedup or norm_utt(t) != norm_utt(dedup[-1]):
            dedup.append(t)
    page_title = " ".join(t for _, _, t in hdr_lines).strip()
    is_skeleton = bool(page_title and len(body_lines) == 0)
    return {
        "utterance": " · ".join(dedup),
        "raw_caption": raw_caption,
        "page_title": page_title,
        "is_skeleton": is_skeleton,
    }
