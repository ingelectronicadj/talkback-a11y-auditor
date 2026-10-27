"""Generador de reportes HTML comparativos multiplataforma (iOS VoiceOver vs Android TalkBack)."""

import datetime
import html
import json
import os
import re
from . import VERSION
from .rules import norm_utt


CMP_CSS = """
* {box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;margin:0;background:#f2f4f7;color:#1d2433}
header{background:#0f172a;color:#fff;padding:20px 24px 22px;border-bottom:3px solid #6366f1}
.hdr-inner{max-width:1240px;margin:0 auto}
.hdr-top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
header h1{font-size:20px;margin:0;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.verbadge{display:inline-block;background:#6366f1;color:#fff;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:16px}
.stat{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:11px 14px}
.stat b{display:block;font-size:22px;color:#a5b4fc}
.stat.warn b{color:#fbbf24}
.stat.crit b{color:#f87171}
.stat.ok b{color:#4ade80}
.stat span{color:#cbd5e1;font-size:11px}
main{max-width:1240px;margin:0 auto;padding:24px}
h2{font-size:14px;margin:28px 0 12px;text-transform:uppercase;letter-spacing:.05em;color:#334155;border-bottom:2px solid #e2e8f0;padding-bottom:6px;display:flex;justify-content:space-between;align-items:center}
.table-wrap{background:#fff;border:1px solid #e2e8f0;border-radius:10px;overflow:hidden;box-shadow:0 1px 2px rgba(15,23,42,.04);margin-bottom:22px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{background:#f8fafc;color:#334155;text-align:left;padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
td{padding:11px 12px;border-bottom:1px solid #f1f5f9;vertical-align:top;line-height:1.45}
tr:last-child td{border-bottom:none}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:700;text-transform:uppercase}
.badge.ios{background:#fee2e2;color:#991b1b}
.badge.and{background:#fef3c7;color:#92400e}
.badge.both{background:#ede9fe;color:#5b21b6}
.badge.ok{background:#dcfce7;color:#166534}
.utt-box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:6px 9px;font-family:'SF Mono',Menlo,monospace;font-size:11.5px;color:#0f172a;margin-top:4px;word-break:break-word}
.dom-code{font-family:'SF Mono',Menlo,monospace;font-size:11px;background:#0f172a;color:#7dd3fc;padding:2px 6px;border-radius:4px;display:inline-block;margin-top:4px;word-break:break-all}
.shot-thumb{width:120px;border:1px solid #cbd5e1;border-radius:6px;margin-top:6px;display:block}
.grid-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.vcard{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;text-decoration:none;color:#0f172a;display:flex;flex-direction:column;gap:8px;box-shadow:0 1px 2px rgba(15,23,42,.04)}
.vcard:hover{border-color:#6366f1;background:#f8fafc}
.vcard h3{margin:0;font-size:15px;color:#1e293b}
.muted{color:#64748b;font-size:11.5px}
"""


def _has_vo_interactive_trait(utt):
    return bool(
        re.search(
            r"\b(button|bot[oó]n|link|enlace|v[ií]nculo|tab|pestaña|text field|campo de texto|toggle|conmutador|header|encabezado)\b",
            (utt or "").lower(),
        )
    )


def _has_tb_interactive_trait(utt):
    return bool(
        re.search(
            r"\b(button|bot[oó]n|link|v[ií]nculo|tab|pestaña|edit box|edici[oó]n|radio|heading|encabezado|term|t[eé]rmino)\b",
            (utt or "").lower(),
        )
    )


def compare_view_dirs(ios_dir, android_dir, out_html=None):
    """Compara steps.json de una vista auditada en iOS VoiceOver y en Android TalkBack y genera un HTML lado a lado."""
    ios_json = os.path.join(ios_dir, "steps.json")
    and_json = os.path.join(android_dir, "steps.json")
    if not (os.path.isfile(ios_json) and os.path.isfile(and_json)):
        return None
    ios_data = json.load(open(ios_json, encoding="utf-8"))
    and_data = json.load(open(and_json, encoding="utf-8"))
    ios_steps = [s for s in ios_data.get("steps", []) if not s.get("is_duplicate")]
    and_steps = [s for s in and_data.get("steps", []) if not s.get("is_duplicate")]
    v_title = (ios_data.get("view_info") or {}).get("title") or (and_data.get("view_info") or {}).get("title") or os.path.basename(ios_dir)
    if not out_html:
        out_html = os.path.join(ios_dir, "comparison_ios_vs_android.html")
    out_parent = os.path.dirname(os.path.abspath(out_html))

    rows = []
    n_ios_only = 0
    n_and_only = 0
    n_both = 0
    n_ok = 0

    # 1. Detectar fragmentación de enlaces compuestos en iOS vs enlace único en Android
    ios_links = [s for s in ios_steps if re.search(r",\s*(link|enlace|v[ií]nculo)(\s*,\s*(image|imagen))?\s*$", (s.get("utterance") or "").lower())]
    and_links = [s for s in and_steps if re.search(r"\.\s*(link|v[ií]nculo)\b", (s.get("utterance") or "").lower())]
    if len(ios_links) >= 10 and len(and_links) >= 2 and len(ios_links) >= len(and_links) * 2:
        n_ios_only += 1
        rows.append({
            "component": "Filas de lista de enlaces (<a data-testid=\"link\">)",
            "dom_sel": "a[data-testid=\"link\"]",
            "ios_step": "Pasos %d-%d (%d paradas Link)" % (ios_links[0]["i"], ios_links[-1]["i"], len(ios_links)),
            "ios_utt": " / ".join(s.get("utterance", "") for s in ios_links[:5]),
            "ios_img": os.path.relpath(os.path.join(ios_dir, ios_links[0]["png"]), out_parent) if ios_links[0].get("png") else "",
            "and_step": "Pasos %d-%d (%d paradas link)" % (and_links[0]["i"], and_links[-1]["i"], len(and_links)),
            "and_utt": and_links[0].get("utterance", ""),
            "and_img": os.path.relpath(os.path.join(android_dir, and_links[0]["png"]), out_parent) if and_links[0].get("png") else "",
            "status_cls": "ios",
            "status_lbl": "Defecto exclusivo iOS (WebKit)",
            "note": "WebKit (WKWebView) no concatena bloques <div> hijos dentro de <a> sin aria-label consolidado, partiendo cada fila en 5 paradas separadas (WCAG 1.3.2 / 2.4.4). Chromium en Android las agrupa en 1 parada.",
        })

    # 2. Emparejar resto de pasos por texto normalizado o selector DOM
    used_and = set()
    for s_ios in ios_steps:
        u_ios = (s_ios.get("utterance") or "").strip()
        if re.search(r"(date:.*value|fecha:.*valor)", u_ios.lower()) and s_ios["i"] > 13:
            continue
        if len(ios_links) >= 10 and s_ios in ios_links[1:]:
            continue
        lbl_ios = (s_ios.get("label") or "").strip()
        dom_ios = s_ios.get("dom") or {}
        n_ios = norm_utt(lbl_ios) or norm_utt(u_ios)
        best_a = None
        for s_and in and_steps:
            if s_and["i"] in used_and:
                continue
            u_and = (s_and.get("utterance") or "").strip()
            lbl_and = (s_and.get("label") or "").strip()
            dom_and = s_and.get("dom") or {}
            n_and = norm_utt(lbl_and) or norm_utt(u_and)
            if dom_ios and dom_and and dom_ios.get("selector") == dom_and.get("selector") and dom_ios.get("label") == dom_and.get("label") and dom_ios.get("label"):
                best_a = s_and
                break
            if n_ios and n_and and (n_ios == n_and or (len(n_ios) >= 5 and (n_ios in n_and or n_and in n_ios))):
                best_a = s_and
                break
        if best_a:
            used_and.add(best_a["i"])
            u_and = (best_a.get("utterance") or "").strip()
            dom_el = dom_ios or best_a.get("dom") or {}
            dtag = (dom_el.get("tag") or "").lower()
            drole = (dom_el.get("role") or "").lower()
            status_cls = "ok"
            status_lbl = "Paridad OK"
            note = "Anuncio equivalente en VoiceOver y TalkBack."

            if re.search(r"(date:.*value|fecha:.*valor)", u_ios.lower()):
                status_cls = "both"
                status_lbl = "Defecto en ambos (Rol distinto)"
                note = "Ambos exponen los puntos <circle> sin salto de bloque (WCAG 2.4.1). WebKit anuncia 'Image' (respeta role='img') y Chromium anuncia 'Button' (por tabindex='0')."
                n_both += 1
            elif ", 0, toggle" in u_ios.lower() and "radio" in u_and.lower():
                status_cls = "both"
                status_lbl = "Doble parada + Valor '0' en iOS"
                note = "Ambos duplican parada en cada píldora rápida (WCAG 1.3.2); además iOS WebKit expone el atributo value='0' con trait 'Toggle' mientras Android anuncia 'Radio button'."
                n_both += 1
            elif (drole == "tab" or " tab" in u_and.lower() or "edit box" in u_and.lower()) and not _has_vo_interactive_trait(u_ios) and _has_tb_interactive_trait(u_and):
                status_cls = "ios"
                status_lbl = "Pérdida de trait en iOS"
                note = "Android TalkBack anuncia el rol interactivo ('tab' / 'Edit box'), pero iOS VoiceOver omite el trait interactivo en WebKit (WCAG 4.1.2)."
                n_ios_only += 1
            elif re.match(r"^[0-9.,]+\s+[A-Z]{3,5}$", u_ios) and re.match(r"^[0-9.,]+$", u_and):
                status_cls = "and"
                status_lbl = "Ticker truncado en Android"
                note = "iOS VoiceOver lee el importe con su ticker ('%s'), mientras Android TalkBack omite el ticker ('%s') (WCAG 1.3.1)." % (u_ios, u_and)
                n_and_only += 1
            elif "current investment, 0" in u_ios.lower() or "current investment. edit box" in u_and.lower():
                status_cls = "both"
                status_lbl = "Falta saldo en ambos (+ sin trait en iOS)"
                note = "En Sell falta interpolar el importe de la inversión actual en el aria-label en ambas plataformas; en iOS además no anuncia 'Text Field'."
                n_both += 1
            elif "select your linked account" in u_ios.lower():
                status_cls = "both"
                status_lbl = "Key heredada en ambos"
                note = "Ambas plataformas invocan la key de Saving Plans ('Select your linked account') en lugar de la key de cuenta seleccionada con saldo."
                n_both += 1
            elif "volumen" in u_ios.lower():
                status_cls = "both"
                status_lbl = "Errata i18n en ambos (+ rol term en Android)"
                note = "Ambas plataformas reproducen la errata 'volumen' en inglés; Android añade el rol semántico '. term' de <dt>."
                n_both += 1
            else:
                n_ok += 1

            rows.append({
                "component": lbl_ios or u_ios[:50],
                "dom_sel": dom_el.get("selector") or dtag or "nativo",
                "ios_step": "Paso %d" % s_ios["i"],
                "ios_utt": u_ios,
                "ios_img": os.path.relpath(os.path.join(ios_dir, s_ios["png"]), out_parent) if s_ios.get("png") else "",
                "and_step": "Paso %d" % best_a["i"],
                "and_utt": u_and,
                "and_img": os.path.relpath(os.path.join(android_dir, best_a["png"]), out_parent) if best_a.get("png") else "",
                "status_cls": status_cls,
                "status_lbl": status_lbl,
                "note": note,
            })

    # 3. Pasos exclusivos de Android (ej. 'Unlabelled. Image' o 'status' vacío)
    for s_and in and_steps:
        if s_and["i"] in used_and:
            continue
        u_and = (s_and.get("utterance") or "").strip()
        if "unlabelled" in u_and.lower() or u_and.lower() in ("status", "estado"):
            n_and_only += 1
            rows.append({
                "component": "Nodo expuesto solo en Chromium (%s)" % u_and[:35],
                "dom_sel": (s_and.get("dom") or {}).get("selector") or "svg / status",
                "ios_step": "No expuesto (omitido por WebKit)",
                "ios_utt": "(WebKit poda este nodo del barrido lineal)",
                "ios_img": "",
                "and_step": "Paso %d" % s_and["i"],
                "and_utt": u_and,
                "and_img": os.path.relpath(os.path.join(android_dir, s_and["png"]), out_parent) if s_and.get("png") else "",
                "status_cls": "and",
                "status_lbl": "Defecto exclusivo Android (Chromium)",
                "note": "Chromium expone el <svg> interno sin aria-hidden como 'Unlabelled. Image' o el <span role='status'> con '\\u200b' como 'status'; WebKit en iOS los ignora.",
            })

    tr_html = []
    for r in rows:
        ios_shot = ('<img class="shot-thumb" src="%s" alt="iOS %s">' % (html.escape(r["ios_img"]), html.escape(r["ios_step"]))) if r["ios_img"] else ""
        and_shot = ('<img class="shot-thumb" src="%s" alt="Android %s">' % (html.escape(r["and_img"]), html.escape(r["and_step"]))) if r["and_img"] else ""
        tr_html.append(
            "<tr>"
            "<td><b>%s</b><br><span class='dom-code'>%s</span></td>"
            "<td><b>%s</b><div class='utt-box'>«%s»</div>%s</td>"
            "<td><b>%s</b><div class='utt-box'>«%s»</div>%s</td>"
            "<td><span class='badge %s'>%s</span><p style='margin:6px 0 0'>%s</p></td>"
            "</tr>"
            % (
                html.escape(r["component"][:90]),
                html.escape(r["dom_sel"]),
                html.escape(r["ios_step"]),
                html.escape(r["ios_utt"]),
                ios_shot,
                html.escape(r["and_step"]),
                html.escape(r["and_utt"]),
                and_shot,
                r["status_cls"],
                html.escape(r["status_lbl"]),
                html.escape(r["note"]),
            )
        )

    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparativa iOS VoiceOver vs Android TalkBack - %(title)s</title>
<style>%(css)s</style></head><body>
<header>
  <div class="hdr-inner">
    <div class="hdr-top">
      <h1>Comparativa iOS VoiceOver (WKWebView) vs Android TalkBack (Chromium) - %(title)s <span class="verbadge">v%(ver)s</span></h1>
    </div>
    <div class="stats">
      <div class="stat"><b>%(n_ios_steps)d vs %(n_and_steps)d</b><span>pasos iOS VoiceOver vs Android TalkBack</span></div>
      <div class="stat crit"><b>%(n_ios_only)d</b><span>diferencias exclusivas iOS (WebKit)</span></div>
      <div class="stat warn"><b>%(n_and_only)d</b><span>diferencias exclusivas Android (Chromium)</span></div>
      <div class="stat warn"><b>%(n_both)d</b><span>defectos compartidos en ambos</span></div>
      <div class="stat ok"><b>%(n_ok)d</b><span>componentes con paridad OK</span></div>
    </div>
  </div>
</header>
<main>
  <h2><span>Matriz comparativa componente a componente (VoiceOver vs TalkBack)</span><span>%(total_rows)d filas comparadas</span></h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th style="width:22%%">Componente / Selector DOM</th>
          <th style="width:26%%">iOS VoiceOver (Xcode Simulator - WKWebView)</th>
          <th style="width:26%%">Android TalkBack (Android Emulator - Chromium)</th>
          <th style="width:26%%">Diagnóstico diferencial (WebKit vs Chromium)</th>
        </tr>
      </thead>
      <tbody>
        %(rows_html)s
      </tbody>
    </table>
  </div>
</main>
</body></html>""" % {
        "title": html.escape(v_title),
        "ver": VERSION,
        "css": CMP_CSS,
        "n_ios_steps": len(ios_steps),
        "n_and_steps": len(and_steps),
        "n_ios_only": n_ios_only,
        "n_and_only": n_and_only,
        "n_both": n_both,
        "n_ok": n_ok,
        "total_rows": len(rows),
        "rows_html": "\n".join(tr_html),
    }
    with open(out_html, "w", encoding="utf-8") as fp:
        fp.write(doc)
    return {
        "path": out_html,
        "title": v_title,
        "ios_steps": len(ios_steps),
        "and_steps": len(and_steps),
        "ios_only": n_ios_only,
        "and_only": n_and_only,
        "both": n_both,
        "ok": n_ok,
    }


def build_comparison_suite(ios_target, android_target, out_path=None):
    """Compara dos carpetas de vista o dos suites completas de reportes (iOS vs Android)."""
    if os.path.isfile(os.path.join(ios_target, "steps.json")) and os.path.isfile(os.path.join(android_target, "steps.json")):
        res = compare_view_dirs(ios_target, android_target, out_html=out_path)
        return res["path"] if res else None

    results = []
    for sub in sorted(os.listdir(ios_target)):
        p_ios = os.path.join(ios_target, sub)
        p_and = os.path.join(android_target, sub)
        if os.path.isdir(p_ios) and os.path.isdir(p_and):
            r = compare_view_dirs(p_ios, p_and)
            if r:
                results.append((sub, r))
    if not results:
        return None
    idx_path = out_path or os.path.join(ios_target, "comparison_index.html")
    idx_parent = os.path.dirname(os.path.abspath(idx_path))
    cards = []
    for sub, r in results:
        rel = os.path.relpath(r["path"], idx_parent)
        cards.append(
            '<a class="vcard" href="%s">'
            '<h3>%s</h3>'
            '<div class="muted">Carpeta: <code>%s</code> · Pasos iOS: <b>%d</b> vs Android: <b>%d</b></div>'
            '<div>'
            '<span class="badge ios">%d solo iOS</span> '
            '<span class="badge and">%d solo Android</span> '
            '<span class="badge both">%d compartidos</span> '
            '<span class="badge ok">%d OK</span>'
            '</div>'
            '</a>'
            % (
                html.escape(rel),
                html.escape(r["title"]),
                html.escape(sub),
                r["ios_steps"],
                r["and_steps"],
                r["ios_only"],
                r["and_only"],
                r["both"],
                r["ok"],
            )
        )
    doc = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Suite Comparativa iOS VoiceOver vs Android TalkBack</title>
<style>%(css)s</style></head><body>
<header>
  <div class="hdr-inner">
    <h1>Suite Comparativa Multiplataforma: iOS VoiceOver (WKWebView) vs Android TalkBack (Chromium) <span class="verbadge">v%(ver)s</span></h1>
  </div>
</header>
<main>
  <h2><span>Vistas comparadas en la suite</span><span>%(n_views)d vistas</span></h2>
  <div class="grid-cards">%(cards)s</div>
</main>
</body></html>""" % {
        "css": CMP_CSS,
        "ver": VERSION,
        "n_views": len(results),
        "cards": "\n".join(cards),
    }
    with open(idx_path, "w", encoding="utf-8") as fp:
        fp.write(doc)
    return idx_path
